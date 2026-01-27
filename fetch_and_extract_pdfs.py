"""
Integration: Contract Truth + PDF Scraper + Text Extraction
Downloads PDFs and Word docs for POOR/MISSING contracts and extracts SOWs.

Usage:
    python fetch_and_extract_pdfs.py --limit 10  # Test
    python fetch_and_extract_pdfs.py             # Full run
"""

import argparse
import re
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone

import fitz  # PyMuPDF
import docx  # python-docx
from openai import OpenAI
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import OpportunityChain, OpportunityAttachment
from polite_sam_scraper import PoliteSAMScraper


def clean_text(text: str) -> str:
    """Clean extracted text."""
    if not text:
        return ""
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove page numbers, headers, footers
    text = re.sub(r'Page \d+ of \d+', '', text, flags=re.IGNORECASE)
    return text.strip()


def extract_text_from_file(file_path: Path) -> Optional[str]:
    """Extract text from PDF or DOCX files."""
    try:
        file_ext = file_path.suffix.lower()
        
        if file_ext == '.pdf':
            # PDF extraction
            doc = fitz.open(file_path)
            text_parts = []
            
            # Extract text from first 20 pages (SOW usually in first pages)
            max_pages = min(20, len(doc))
            
            for page_num in range(max_pages):
                page = doc[page_num]
                text = page.get_text()
                text_parts.append(text)
            
            doc.close()
            full_text = "\n".join(text_parts)
            
        elif file_ext in ['.docx', '.doc']:
            # Word document extraction
            doc = docx.Document(file_path)
            text_parts = []
            for paragraph in doc.paragraphs:
                text_parts.append(paragraph.text)
            full_text = "\n".join(text_parts)
            
        else:
            return None
        
        cleaned = clean_text(full_text)
        
        # Must be substantial
        if len(cleaned) < 500:
            return None
        
        return cleaned
        
    except Exception as e:
        print(f"      ⚠️  File extraction error: {str(e)[:100]}")
        return None


def is_sow_related_file(filename: str) -> bool:
    """Check if filename suggests it contains SOW."""
    if not filename or filename == 'None':
        return False
    
    fn = str(filename).lower()  # Convert to string safely
    
    # High priority keywords
    sow_keywords = [
        'sow', 'statement of work', 'scope of work',
        'rfp', 'request for proposal',
        'solicitation', 'rfq', 'request for quote',
        'pws', 'performance work statement'
    ]
    
    if any(keyword in fn for keyword in sow_keywords):
        return True
    
    # Skip obvious non-SOW files
    skip_keywords = [
        'amendment', 'amend', 'mod', 'modification',
        'wage', 'sf-', 'form', 'clause',
        'questions', 'q&a', 'addendum', 'add-'
    ]
    
    if any(keyword in fn for keyword in skip_keywords):
        return False
    
    # Accept PDFs and Word docs
    return fn.endswith(('.pdf', '.docx', '.doc'))

def extract_sow_with_gpt(text: str, openai_client: OpenAI) -> Optional[str]:
    """Use GPT to extract SOW from document text."""
    
    # Truncate if too long
    if len(text) > 12000:
        text = text[:12000] + "\n\n[Text truncated...]"
    
    prompt = f"""You are analyzing text extracted from a government contract document. Your job is to extract the Statement of Work (SOW) or Performance Work Statement (PWS).

Here is the extracted text:

{text}

Extract a clear, concise summary of the Statement of Work. Focus on:
- What services/products are being procured
- Scope of work and key requirements
- Deliverables and performance expectations

If there is NO useful SOW information (just boilerplate, forms, or unreadable text), respond with: NO_SOW_FOUND

Otherwise, provide a clean 2-3 paragraph summary of the statement of work."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a government contracting expert who extracts statements of work."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=600
        )
        
        extracted = response.choices[0].message.content.strip()
        
        if "NO_SOW_FOUND" in extracted:
            return None
        
        if len(extracted) < 100:
            return None
        
        return extracted
        
    except Exception as e:
        print(f"      ⚠️  GPT error: {str(e)[:100]}")
        return None


def assess_quality(description: str) -> str:
    """Assess description quality."""
    if not description:
        return "MISSING"
    
    if len(description) < 50:
        return "POOR"
    
    # Check for garbage patterns
    garbage = ['see attached', 'see attachment', 'refer to']
    if any(g in description.lower() for g in garbage):
        return "POOR"
    
    return "GOOD"


def process_contracts(
    db: Session,
    scraper: PoliteSAMScraper,
    openai_client: OpenAI,
    limit: Optional[int] = None,
    verbose: bool = True
):
    """Main processing logic."""
    
    if verbose:
        print("=" * 70)
        print("PDF/DOCX EXTRACTION PIPELINE - FIX #4")
        print("=" * 70)
        print()
    
    # Get POOR/MISSING contracts
    query = db.query(OpportunityChain).filter(
        OpportunityChain.base_description_quality.in_(['POOR', 'MISSING'])
    )
    
    if limit:
        query = query.limit(limit)
    
    contracts = query.all()
    
    if verbose:
        print(f"📊 Found {len(contracts)} contracts to process")
        if limit:
            print(f"   Limited to {limit} for testing")
        print()
    
    improved_count = 0
    no_pdfs_count = 0
    extraction_failed_count = 0
    
    for idx, contract in enumerate(contracts, 1):
        if verbose:
            print(f"[{idx}/{len(contracts)}] {contract.solicitation_number}...")
            print(f"   Notice ID: {contract.base_notice_id}")
        
        # Step 1: Fetch attachments (now includes type: "link")
        try:
            attachments, stats = scraper.get_attachments(contract.base_notice_id)
            
            if verbose:
                print(f"   📎 Found {len(attachments)} attachment(s)")
                for att in attachments:
                    print(f"      DEBUG: filename='{att['filename']}'")
            
            if not attachments:
                no_pdfs_count += 1
                if verbose:
                    print(f"   ❌ No downloadable attachments")
                continue
            
            # Step 2: Filter for SOW-related files
            sow_files = [a for a in attachments if is_sow_related_file(a['filename'])]
            
            if not sow_files:
                if verbose:
                    print(f"   ⚠️  No SOW keywords in filenames, will try all attachments")
                sow_files = attachments 
            
            if not sow_files:
                no_pdfs_count += 1
                if verbose:
                    print(f"   ❌ No SOW-related documents found")
                continue
            
            if verbose:
                print(f"   📄 Processing {len(sow_files)} SOW file(s)")
            
            # Step 3: Download and extract
            extracted_sow = None
            
            for sow_file in sow_files:
                if verbose:
                    print(f"      Downloading: {sow_file['filename']}")
                
                file_path = scraper.download_attachment(
                    resource_id=sow_file['resource_id'],
                    filename=sow_file['filename'],
                    use_cache=True
                )
                
                if not file_path:
                    continue
                
                # Extract text (handles both PDF and DOCX)
                if verbose:
                    print(f"      Extracting text...")
                
                text = extract_text_from_file(file_path)
                
                if not text:
                    if verbose:
                        print(f"      ⚠️  Could not extract text")
                    continue
                
                if verbose:
                    print(f"      Using GPT to extract SOW...")
                
                # Extract SOW with GPT
                extracted_sow = extract_sow_with_gpt(text, openai_client)
                
                if extracted_sow:
                    # Store attachment info
                    attachment_record = OpportunityAttachment(
                        chain_id=contract.id,
                        filename=sow_file['filename'],
                        file_type=file_path.suffix.upper().replace('.', ''),
                        file_size_bytes=sow_file.get('size'),
                        download_url=f"https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{sow_file['resource_id']}/download",
                        is_sow=True,
                        downloaded=True,
                        extracted=True
                    )
                    db.add(attachment_record)
                    
                    break  # Found SOW, stop processing more files
            
            # Step 4: Update contract if we got something
            if extracted_sow:
                quality = assess_quality(extracted_sow)
                
                if quality == "GOOD":
                    contract.base_description = extracted_sow
                    contract.base_description_quality = "GOOD"
                    contract.needs_sow_extraction = False
                    contract.has_attachments = True
                    contract.attachment_count = len(attachments)
                    contract.attachments_fetched_at = datetime.now(timezone.utc)
                    contract.updated_at = datetime.now(timezone.utc)
                    
                    improved_count += 1
                    
                    if verbose:
                        preview = extracted_sow[:150] + "..." if len(extracted_sow) > 150 else extracted_sow
                        print(f"   ✅ Extracted SOW! {contract.base_description_quality} → GOOD")
                        print(f"      Preview: {preview}")
                else:
                    extraction_failed_count += 1
                    if verbose:
                        print(f"   ⚠️  Extracted but quality still {quality}")
            else:
                extraction_failed_count += 1
                if verbose:
                    print(f"   ❌ Could not extract useful SOW")
            
        except Exception as e:
            extraction_failed_count += 1
            if verbose:
                print(f"   ❌ Error: {str(e)[:100]}")
        
        # Commit every 5
        if idx % 5 == 0:
            db.commit()
        
        if verbose and idx % 5 == 0:
            print()
    
    db.commit()
    
    if verbose:
        print()
        print("=" * 70)
        print("✅ PDF/DOCX EXTRACTION COMPLETE")
        print("=" * 70)
        print(f"   Improved to GOOD: {improved_count}")
        print(f"   No documents found: {no_pdfs_count}")
        print(f"   Extraction failed: {extraction_failed_count}")
        print(f"   Total processed: {len(contracts)}")
        
        if len(contracts) > 0:
            success_rate = (improved_count / len(contracts)) * 100
            print(f"   Success rate: {success_rate:.1f}%")
        
        print()
        
        # Show updated stats
        from sqlalchemy import func
        stats = db.query(
            OpportunityChain.base_description_quality,
            func.count(OpportunityChain.id)
        ).group_by(OpportunityChain.base_description_quality).all()
        
        total = sum(count for _, count in stats)
        print("📊 Overall Database Quality:")
        for quality, count in stats:
            pct = (count / total * 100) if total > 0 else 0
            print(f"   {quality}: {count} ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Extract SOW from PDFs and Word docs")
    parser.add_argument('--limit', type=int, default=None, help="Test on N contracts")
    parser.add_argument('--quiet', action='store_true', help="Suppress output")
    parser.add_argument('--respect-business-hours', action='store_true', help="Only run 9-5 ET weekdays")
    
    args = parser.parse_args()
    
    # Initialize
    import os
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    scraper = PoliteSAMScraper(
        cache_dir=Path("./sam_cache"),
        contact_email="your-email@yourcompany.com"  # UPDATE THIS
    )
    
    db = SessionLocal()
    
    try:
        if args.respect_business_hours and not scraper.is_business_hours():
            print("⏸️  Outside business hours - exiting")
            return
        
        process_contracts(db, scraper, openai_client, limit=args.limit, verbose=not args.quiet)
    finally:
        scraper.close()
        db.close()


if __name__ == "__main__":
    main()