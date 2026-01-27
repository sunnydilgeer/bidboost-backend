"""
AI SOW Extraction - Fix #3
Uses GPT-4 to extract statement of work from amendment chains.

Usage:
    python extract_sow_with_ai.py data/ContractOpportunitiesFullCSV.csv --limit 10
    python extract_sow_with_ai.py data/ContractOpportunitiesFullCSV.csv
"""

import argparse
import time
import re
import csv
from typing import Optional, List, Dict
from datetime import datetime, timezone
from collections import defaultdict

from openai import OpenAI
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import OpportunityChain


def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def assess_description_quality(description: str) -> str:
    """Assess quality of description text."""
    if not description:
        return "MISSING"
    
    clean_desc = clean_html(description)
    
    if len(clean_desc) < 50:
        return "POOR"
    
    # Check for garbage patterns
    garbage_keywords = ['see attached', 'see attachment', 'refer to']
    text_lower = clean_desc.lower()
    
    # Must not start with garbage
    if any(text_lower.startswith(keyword) for keyword in garbage_keywords):
        return "POOR"
    
    return "GOOD"


def read_notices_from_csv(csv_path: str, solicitation_numbers: List[str]) -> Dict[str, List[Dict]]:
    """
    Read all notices for given solicitation numbers from CSV.
    
    Returns:
        Dict mapping solicitation_number -> list of notice dicts
    """
    
    sol_to_notices = defaultdict(list)
    
    with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            sol_num = row.get('Sol#', '').strip()
            
            if sol_num in solicitation_numbers:
                sol_to_notices[sol_num].append(row)
    
    return dict(sol_to_notices)


def extract_sow_with_gpt(notices: List[Dict], openai_client: OpenAI) -> Optional[str]:
    """
    Use GPT-4 to extract statement of work from multiple notices.
    
    Args:
        notices: List of notice dictionaries from CSV
        openai_client: OpenAI client
    
    Returns:
        Extracted SOW or None if extraction fails
    """
    
    # Combine all notice information
    combined_text = []
    
    for idx, notice in enumerate(notices, 1):
        title = clean_html(notice.get('Title', ''))
        desc = clean_html(notice.get('Description', ''))
        notice_type = notice.get('Type', '')
        base_type = notice.get('BaseType', '')
        
        notice_text = f"""
Notice {idx} ({base_type} - {notice_type}):
Title: {title}
Description: {desc}
"""
        combined_text.append(notice_text.strip())
    
    full_text = "\n\n".join(combined_text)
    
    # Limit text length to avoid token limits
    if len(full_text) > 8000:
        full_text = full_text[:8000] + "\n\n[Text truncated...]"
    
    # Prompt GPT-4 to extract SOW
    prompt = f"""You are analyzing a series of government contract notices. Some may say "see attached" or be amendments. Your job is to extract the actual Statement of Work (SOW) or project description.

Here are all the notices for this solicitation:

{full_text}

Extract the clearest, most complete statement of work from these notices. If multiple notices contain SOW information, combine them. Focus on:
- What services/products are being procured
- Scope of work
- Key requirements
- Deliverables

If ALL notices only say "see attached" or contain no useful SOW information, respond with: NO_SOW_FOUND

Otherwise, provide a clean 2-3 paragraph summary of the statement of work."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Cheaper, faster for this task
            messages=[
                {"role": "system", "content": "You are a government contracting expert who extracts statements of work from procurement notices."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        extracted = response.choices[0].message.content.strip()
        
        if "NO_SOW_FOUND" in extracted:
            return None
        
        # Clean up the response
        extracted = clean_html(extracted)
        
        # Must be substantial
        if len(extracted) < 100:
            return None
        
        return extracted
        
    except Exception as e:
        print(f"      ⚠️  GPT error: {str(e)[:100]}")
        return None


def improve_descriptions(
    db: Session,
    csv_path: str,
    limit: Optional[int] = None,
    verbose: bool = True
):
    """
    Extract SOW using GPT-4 for POOR/MISSING contracts.
    """
    
    if verbose:
        print("=" * 70)
        print("AI SOW EXTRACTION - FIX #3")
        print("=" * 70)
        print()
    
    # Initialize OpenAI
    import os
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY environment variable not set")
        return
    
    openai_client = OpenAI(api_key=api_key)
    
    # Get all POOR/MISSING contracts
    query = db.query(OpportunityChain).filter(
        OpportunityChain.base_description_quality.in_(['POOR', 'MISSING'])
    )
    
    if limit:
        query = query.limit(limit)
    
    contracts = query.all()
    
    if verbose:
        print(f"📊 Found {len(contracts)} contracts with POOR/MISSING descriptions")
        if limit:
            print(f"   Processing first {limit} for testing")
        print()
        print("📖 Reading notices from CSV...")
    
    # Get solicitation numbers
    sol_numbers = [c.solicitation_number for c in contracts]
    
    # Read all notices for these solicitations
    sol_to_notices = read_notices_from_csv(csv_path, sol_numbers)
    
    if verbose:
        print(f"   Found notices for {len(sol_to_notices)} solicitations")
        print()
    
    improved_count = 0
    failed_count = 0
    
    for idx, contract in enumerate(contracts, 1):
        if verbose:
            print(f"[{idx}/{len(contracts)}] {contract.solicitation_number}...")
        
        # Get all notices for this solicitation
        notices = sol_to_notices.get(contract.solicitation_number, [])
        
        if not notices:
            failed_count += 1
            if verbose:
                print(f"   ❌ No notices found in CSV")
            continue
        
        if verbose:
            print(f"   🔍 Analyzing {len(notices)} notices with GPT-4...")
        
        # Extract SOW with GPT
        extracted_sow = extract_sow_with_gpt(notices, openai_client)
        
        if extracted_sow:
            # Assess quality
            quality = assess_description_quality(extracted_sow)
            
            if quality == "GOOD":
                # Update database
                contract.base_description = extracted_sow
                contract.base_description_quality = "GOOD"
                contract.needs_sow_extraction = False
                contract.updated_at = datetime.now(timezone.utc)
                
                improved_count += 1
                
                if verbose:
                    preview = extracted_sow[:150] + "..." if len(extracted_sow) > 150 else extracted_sow
                    print(f"   ✅ Extracted SOW! {contract.base_description_quality} → GOOD")
                    print(f"      Preview: {preview}")
            else:
                failed_count += 1
                if verbose:
                    print(f"   ⚠️  Extracted but quality still {quality}")
        else:
            failed_count += 1
            if verbose:
                print(f"   ❌ Could not extract useful SOW")
        
        # Commit every 5 updates
        if idx % 5 == 0:
            db.commit()
        
        # Rate limiting for OpenAI
        time.sleep(0.5)
        
        if verbose and idx % 5 == 0:
            print()
    
    db.commit()
    
    if verbose:
        print()
        print("=" * 70)
        print("✅ AI SOW EXTRACTION COMPLETE")
        print("=" * 70)
        print(f"   Improved to GOOD: {improved_count}")
        print(f"   Failed to extract: {failed_count}")
        print(f"   Total processed: {len(contracts)}")
        
        # Calculate improvement
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
    parser = argparse.ArgumentParser(description="Extract SOW using AI from notice chains")
    parser.add_argument('csv_file', help="Path to ContractOpportunitiesFullCSV.csv")
    parser.add_argument('--limit', type=int, default=None, help="Process only first N contracts (for testing)")
    parser.add_argument('--quiet', action='store_true', help="Suppress output")
    
    args = parser.parse_args()
    
    db = SessionLocal()
    
    try:
        improve_descriptions(db, args.csv_file, limit=args.limit, verbose=not args.quiet)
    finally:
        db.close()


if __name__ == "__main__":
    main()