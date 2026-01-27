"""
External Attachment Scraper
Downloads files from external links (not SAM-hosted).

Usage:
    python fetch_external_attachments.py --limit 1
"""

import argparse
import re
import requests
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

import docx  # python-docx
import fitz  # PyMuPDF
from openai import OpenAI
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import OpportunityChain, OpportunityAttachment
from polite_sam_scraper import PoliteSAMScraper


def get_all_attachments_including_external(notice_id: str, scraper: PoliteSAMScraper):
    """Get ALL attachments including external links."""
    api_url = f"https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources"
    
    try:
        response = scraper.client.request("GET", api_url)
        data = response.json()
        
        all_attachments = []
        opp_list = data.get("_embedded", {}).get("opportunityAttachmentList", [])
        
        for opp in opp_list:
            for att in opp.get("attachments", []):
                resource_id = att.get('resourceId')
                
                # Construct download URL from resourceId
                download_url = None
                if resource_id:
                    download_url = f"https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{resource_id}/download"
                
                all_attachments.append({
                    'filename': att.get('name', f"attachment_{resource_id}.pdf"),
                    'type': att.get('type'),
                    'url': download_url,
                    'resource_id': resource_id,
                    'size': att.get('size'),
                    'mime_type': att.get('mimeType'),
                })
        
        return all_attachments
        
    except Exception as e:
        print(f"      ⚠️  Error fetching attachments: {e}")
        return []

def download_external_file(url: str, filename: str, cache_dir: Path) -> Optional[Path]:
    """Download file from external URL."""
    try:
        # Create safe filename
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', filename)[:180]
        filepath = cache_dir / safe_name
        
        # Check cache
        if filepath.exists():
            print(f"      ✅ Found in cache: {safe_name}")
            return filepath
        
        print(f"      📥 Downloading from external URL...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Save file
        with open(filepath, 'wb') as f:
            f.write(response.content)
        
        print(f"      ✅ Downloaded: {safe_name} ({len(response.content) / 1024:.1f} KB)")
        return filepath
        
    except Exception as e:
        print(f"      ❌ Download failed: {str(e)[:100]}")
        return None


def extract_text_from_file(file_path: Path) -> Optional[str]:
    """Extract text from PDF or DOCX files."""
    try:
        file_ext = file_path.suffix.lower()
        
        if file_ext == '.pdf':
            doc = fitz.open(file_path)
            text_parts = []
            max_pages = min(20, len(doc))
            for page_num in range(max_pages):
                page = doc[page_num]
                text = page.get_text()
                text_parts.append(text)
            doc.close()
            full_text = "\n".join(text_parts)
            
        elif file_ext in ['.docx', '.doc']:
            doc = docx.Document(file_path)
            text_parts = []
            for paragraph in doc.paragraphs:
                text_parts.append(paragraph.text)
            full_text = "\n".join(text_parts)
            
        else:
            return None
        
        # Clean text
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        
        if len(full_text) < 500:
            return None
        
        return full_text
        
    except Exception as e:
        print(f"      ⚠️  Extraction error: {str(e)[:100]}")
        return None


def extract_sow_with_gpt(text: str, openai_client: OpenAI) -> Optional[str]:
    """Use GPT to extract SOW."""
    if len(text) > 12000:
        text = text[:12000] + "\n\n[Text truncated...]"
    
    prompt = f"""You are analyzing text from a government contract document. Extract the Statement of Work (SOW) or Performance Work Statement (PWS).

Here is the extracted text:

{text}

Provide a clear 2-3 paragraph summary of:
- What services/products are being procured
- Scope of work and key requirements
- Deliverables

If NO useful SOW information exists, respond with: NO_SOW_FOUND"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a government contracting expert."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=600
        )
        
        extracted = response.choices[0].message.content.strip()
        
        if "NO_SOW_FOUND" in extracted or len(extracted) < 100:
            return None
        
        return extracted
        
    except Exception as e:
        print(f"      ⚠️  GPT error: {str(e)[:100]}")
        return None


def assess_quality(description: str) -> str:
    """Assess description quality."""
    if not description or len(description) < 50:
        return "POOR"
    if any(kw in description.lower() for kw in ['see attached', 'refer to']):
        return "POOR"
    return "GOOD"


def process_contracts(
    db: Session,
    scraper: PoliteSAMScraper,
    openai_client: OpenAI,
    cache_dir: Path,
    limit: Optional[int] = None
):
    """Main processing logic."""
    
    print("=" * 70)
    print("EXTERNAL ATTACHMENT EXTRACTION")
    print("=" * 70)
    print()
    
    # Get POOR/MISSING contracts
    query = db.query(OpportunityChain).filter(
        OpportunityChain.base_description_quality.in_(['POOR', 'MISSING'])
    )
    
    if limit:
        query = query.limit(limit)
    
    contracts = query.all()
    
    print(f"📊 Found {len(contracts)} contracts")
    if limit:
        print(f"   Testing with first {limit}")
    print()
    
    improved_count = 0
    
    for idx, contract in enumerate(contracts, 1):
        print(f"[{idx}/{len(contracts)}] {contract.solicitation_number}")
        print(f"   Notice: {contract.base_notice_id}")
        
        # Get ALL attachments (including external)
        all_attachments = get_all_attachments_including_external(
            contract.base_notice_id, 
            scraper
        )
        
        print(f"   📎 Found {len(all_attachments)} total attachment(s)")
        
        if not all_attachments:
            print(f"   ❌ No attachments")
            continue
        
        # Process each attachment
        extracted_sow = None
        
        for att in all_attachments:
            filename = att.get('filename', 'unknown')
            att_type = att.get('type', '')
            url = att.get('url')
            
            print(f"   📄 {filename} (type: {att_type})")
            
            # Skip if it's a SAM-hosted file (already tried)
            if att_type.lower() == 'file':
                print(f"      ⏭️  SAM-hosted (already processed)")
                continue
            
            # Must have external URL
            if not url:
                print(f"      ❌ No URL")
                continue
            
            # Download external file
            file_path = download_external_file(url, filename, cache_dir)
            
            if not file_path:
                continue
            
            # Extract text
            print(f"      📖 Extracting text...")
            text = extract_text_from_file(file_path)
            
            if not text:
                print(f"      ⚠️  No text extracted")
                continue
            
            print(f"      🤖 Using GPT to extract SOW...")
            extracted_sow = extract_sow_with_gpt(text, openai_client)
            
            if extracted_sow:
                print(f"      ✅ Found SOW!")
                break
        
        # Update database if we got something
        if extracted_sow and assess_quality(extracted_sow) == "GOOD":
            contract.base_description = extracted_sow
            contract.base_description_quality = "GOOD"
            contract.needs_sow_extraction = False
            contract.updated_at = datetime.now(timezone.utc)
            
            improved_count += 1
            
            preview = extracted_sow[:150] + "..." if len(extracted_sow) > 150 else extracted_sow
            print(f"   ✅ Updated to GOOD")
            print(f"      Preview: {preview}")
        
        if idx % 5 == 0:
            db.commit()
        
        print()
    
    db.commit()
    
    print("=" * 70)
    print(f"✅ Improved: {improved_count}/{len(contracts)}")
    
    # Show stats
    from sqlalchemy import func
    stats = db.query(
        OpportunityChain.base_description_quality,
        func.count(OpportunityChain.id)
    ).group_by(OpportunityChain.base_description_quality).all()
    
    total = sum(count for _, count in stats)
    print("\n📊 Overall Quality:")
    for quality, count in stats:
        pct = (count / total * 100) if total > 0 else 0
        print(f"   {quality}: {count} ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()
    
    import os
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    cache_dir = Path("./external_cache")
    cache_dir.mkdir(exist_ok=True)
    
    scraper = PoliteSAMScraper(
        cache_dir=Path("./sam_cache"),
        contact_email="your-email@example.com"
    )
    
    db = SessionLocal()
    
    try:
        process_contracts(db, scraper, openai_client, cache_dir, limit=args.limit)
    finally:
        scraper.close()
        db.close()


if __name__ == "__main__":
    main()