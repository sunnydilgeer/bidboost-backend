"""
Contract Truth Layer Builder
Groups SAM.gov notices by solicitation number and identifies base notices.

Usage:
    python build_contract_truth.py data/ContractOpportunitiesFullCSV.csv
    python build_contract_truth.py data/ContractOpportunitiesFullCSV.csv --limit 100
    python build_contract_truth.py data/ContractOpportunitiesFullCSV.csv --quiet
"""

import csv
import re
import argparse
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import OpportunityChain


# Amendment detection keywords
AMENDMENT_KEYWORDS = [
    'amendment', 'amend', 'modification', 'mod ', 'mod-', 'revised', 
    'see attached', 'see attachment', 'addendum', 'cancellation',
    'cancel', 'updated', 'correction', 'change order'
]

# Base notice types (priority order)
BASE_TYPES_PRIORITY = [
    'Combined Synopsis/Solicitation',
    'Solicitation',
    'Presolicitation',
    'Sources Sought'
]


def clean_html(text: str) -> str:
    """Remove HTML tags."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def has_amendment_keywords(text: str) -> bool:
    """Check if text contains amendment indicators."""
    if not text:
        return False
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in AMENDMENT_KEYWORDS)


def assess_description_quality(description: str) -> str:
    """Assess quality of description text."""
    if not description:
        return "MISSING"
    
    clean_desc = clean_html(description)
    
    if len(clean_desc) < 50:
        return "POOR"
    
    if has_amendment_keywords(clean_desc):
        return "POOR"
    
    # Check for common garbage patterns
    garbage_patterns = [
        r'^see\s+(attached|attachment)',
        r'^refer\s+to',
        r'^amendment\s+\d+',
        r'^modification\s+\d+',
    ]
    
    for pattern in garbage_patterns:
        if re.search(pattern, clean_desc.lower()):
            return "POOR"
    
    return "GOOD"


def find_base_notice(notices: List[Dict]) -> Dict:
    """
    Find the base notice from a group of related notices.
    Now scans ALL notices for best description, not just base types.
    
    Priority logic:
    1. Find notices with GOOD quality descriptions
    2. Among GOOD ones, prefer non-amendments
    3. Among those, prefer Solicitation/Presolicitation types
    4. Pick the longest description
    """
    
    # Step 1: Score all notices by description quality
    scored = []
    for notice in notices:
        desc = notice.get('Description', '')
        quality = assess_description_quality(desc)
        
        scored.append({
            'notice': notice,
            'quality': quality,
            'desc_length': len(clean_html(desc)),
            'base_type': notice.get('BaseType', ''),
            'is_amendment': has_amendment_keywords(
                f"{notice.get('Title', '')} {notice.get('Type', '')}"
            )
        })
    
    # Step 2: Prioritize GOOD descriptions
    good_ones = [s for s in scored if s['quality'] == 'GOOD']
    
    if good_ones:
        # Among good ones, prefer:
        # 1. Non-amendments
        # 2. Solicitation/Presolicitation types
        # 3. Longest description
        
        non_amendments = [s for s in good_ones if not s['is_amendment']]
        if non_amendments:
            good_ones = non_amendments
        
        # Sort by base type priority, then length
        type_priority = {
            'Combined Synopsis/Solicitation': 4,
            'Solicitation': 3,
            'Presolicitation': 2,
            'Sources Sought': 1
        }
        
        return max(good_ones, key=lambda s: (
            type_priority.get(s['base_type'], 0),
            s['desc_length']
        ))['notice']
    
    # Step 3: No GOOD descriptions - fall back to old logic
    # Try each base type in priority order
    for base_type in BASE_TYPES_PRIORITY:
        type_matches = [s for s in scored if s['notice'].get('BaseType') == base_type]
        
        if not type_matches:
            continue
        
        # Filter out obvious amendments
        non_amendments = [s for s in type_matches if not s['is_amendment']]
        
        if non_amendments:
            # Pick longest description
            return max(non_amendments, key=lambda s: s['desc_length'])['notice']
        
        # Fallback: longest description even if amendment
        return max(type_matches, key=lambda s: s['desc_length'])['notice']
    
    # Ultimate fallback: longest description overall
    return max(scored, key=lambda s: s['desc_length'])['notice']


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse SAM.gov date string to UTC timezone-aware datetime."""
    if not date_str:
        return None
    try:
        # Handle formats like "2026-01-22 23:08:53.629-05"
        clean_str = date_str.split('.')[0].replace(' ', 'T')
        
        # Try parsing with timezone
        try:
            dt = datetime.fromisoformat(clean_str)
        except:
            # Fallback to just date
            dt = datetime.strptime(clean_str.split('T')[0], '%Y-%m-%d')
        
        # Ensure timezone-aware (convert to UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        
        return dt
        
    except:
        return None


def read_csv_by_solicitation(filepath: str) -> Dict[str, List[Dict]]:
    """Group CSV rows by solicitation number."""
    
    grouped = defaultdict(list)
    
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            sol_num = row.get('Sol#', '').strip()
            
            if not sol_num:
                continue
            
            grouped[sol_num].append(row)
    
    return dict(grouped)

def build_truth_table(csv_filepath: str, db: Session, verbose: bool = True, limit: Optional[int] = None):
    """Main function to build contract truth table."""
    
    if verbose:
        print("=" * 70)
        print("CONTRACT TRUTH LAYER BUILDER")
        print("=" * 70)
        print(f"📂 Input: {csv_filepath}")
        if limit:
            print(f"🔬 Test mode: Processing first {limit} solicitations")
        print()
    
    # Read and group notices
    if verbose:
        print("📖 Grouping notices by solicitation number...")
    
    grouped_notices = read_csv_by_solicitation(csv_filepath)
    
    if verbose:
        print(f"   Found {len(grouped_notices)} unique solicitation numbers")
        print()
    
    # Apply limit if specified
    if limit:
        grouped_notices = dict(list(grouped_notices.items())[:limit])
        if verbose:
            print(f"   Limited to first {len(grouped_notices)} solicitations")
            print()
    
    # Process each solicitation
    if verbose:
        print("🔨 Identifying base notices and capturing metadata...")
    
    created_count = 0
    updated_count = 0
    needs_sow_count = 0
    
    for idx, (sol_num, notices) in enumerate(grouped_notices.items(), 1):
        # Find base notice (now scans ALL notices for best description)
        base = find_base_notice(notices)
        
        # Assess description quality
        description = clean_html(base.get('Description', ''))
        quality = assess_description_quality(description)
        needs_sow = quality != "GOOD"
        
        if needs_sow:
            needs_sow_count += 1
        
        # Get latest closing date from all notices in chain
        closing_dates = [
            parse_date(n.get('ResponseDeadLine', ''))
            for n in notices
        ]
        valid_dates = [d for d in closing_dates if d is not None]
        latest_closing = max(valid_dates) if valid_dates else None
        
        # ✅ NEW: Extract metadata from base notice
        # ✅ FIXED: Extract metadata from base notice with truncation
        base_agency = (base.get('Sub-Tier', '') or '')[:255]
        base_office = (base.get('Office', '') or '')[:500]  # TEXT type, can be longer
        base_naics = (base.get('NaicsCode', '') or '')[:10]
        base_psc = (base.get('ClassificationCode', '') or '')[:10]
        base_set_aside = (base.get('SetASide', '') or '')[:100]
        base_state = (base.get('PopState', '') or '')[:50]
        base_city = (base.get('PopCity', '') or '')[:100]
        base_contact_name = (base.get('PrimaryContactFullname', '') or '')[:200]  # ✅ TRUNCATE
        base_contact_email = (base.get('PrimaryContactEmail', '') or '')[:200]
        base_contact_phone = (base.get('PrimaryContactPhone', '') or '')[:50]

        # Upsert to database
        existing = db.query(OpportunityChain).filter_by(solicitation_number=sol_num).first()
        
        if existing:
            # Update existing chain
            existing.base_notice_id = base.get('NoticeId', '')
            existing.base_sol_number = base.get('Sol#', '')
            existing.base_description = description
            existing.base_posted_date = parse_date(base.get('PostedDate', ''))
            existing.base_type = base.get('BaseType', '')
            
            # ✅ NEW: Update metadata fields
            existing.base_agency = base_agency
            existing.base_office = base_office
            existing.base_naics = base_naics
            existing.base_psc = base_psc
            existing.base_set_aside = base_set_aside
            existing.base_state = base_state
            existing.base_city = base_city
            existing.base_contact_name = base_contact_name
            existing.base_contact_email = base_contact_email
            existing.base_contact_phone = base_contact_phone
            
            existing.notice_count = len(notices)
            existing.has_amendments = len(notices) > 1
            existing.latest_closing_date = latest_closing
            existing.base_description_quality = quality
            existing.needs_sow_extraction = needs_sow
            existing.updated_at = datetime.now(timezone.utc)
            
            updated_count += 1
        else:
            # Create new chain
            chain = OpportunityChain(
                solicitation_number=sol_num,
                base_notice_id=base.get('NoticeId', ''),
                base_sol_number=base.get('Sol#', ''),
                base_description=description,
                base_posted_date=parse_date(base.get('PostedDate', '')),
                base_type=base.get('BaseType', ''),
                
                # ✅ NEW: Add metadata fields
                base_agency=base_agency,
                base_office=base_office,
                base_naics=base_naics,
                base_psc=base_psc,
                base_set_aside=base_set_aside,
                base_state=base_state,
                base_city=base_city,
                base_contact_name=base_contact_name,
                base_contact_email=base_contact_email,
                base_contact_phone=base_contact_phone,
                
                notice_count=len(notices),
                has_amendments=len(notices) > 1,
                latest_closing_date=latest_closing,
                base_description_quality=quality,
                needs_sow_extraction=needs_sow
            )
            
            db.add(chain)
            created_count += 1
        
        # Progress indicator
        if verbose and idx % 100 == 0:
            print(f"   Processed {idx:,} / {len(grouped_notices):,} chains...")
        
        if idx % 1000 == 0:
            db.commit()
    
    db.commit()
    
    if verbose:
        print()
        print("=" * 70)
        print("✅ TRUTH TABLE BUILT (WITH METADATA)")
        print("=" * 70)
        print(f"   Created: {created_count} new chains")
        print(f"   Updated: {updated_count} existing chains")
        print(f"   Total opportunities: {created_count + updated_count}")
        print()
        print(f"📊 Description Quality (this run):")
        
        # Get stats only for processed solicitations
        processed_sols = list(grouped_notices.keys())
        from sqlalchemy import func
        stats = db.query(
            OpportunityChain.base_description_quality,
            func.count(OpportunityChain.id)
        ).filter(
            OpportunityChain.solicitation_number.in_(processed_sols)
        ).group_by(OpportunityChain.base_description_quality).all()
        
        total_processed = sum(count for _, count in stats)
        for quality, count in stats:
            pct = (count / total_processed * 100) if total_processed > 0 else 0
            print(f"   {quality}: {count} ({pct:.1f}%)")
        
        print()
        needs_pct = (needs_sow_count / total_processed * 100) if total_processed > 0 else 0
        print(f"🔍 Needs SOW extraction: {needs_sow_count} contracts ({needs_pct:.1f}%)")
        
        # ✅ NEW: Show metadata capture stats
        print()
        print(f"📋 Metadata Capture Stats:")
        
        # Count how many records have each field
        metadata_stats = db.query(
            func.sum(func.case((OpportunityChain.base_agency != None, 1), else_=0)).label('has_agency'),
            func.sum(func.case((OpportunityChain.base_naics != None, 1), else_=0)).label('has_naics'),
            func.sum(func.case((OpportunityChain.base_state != None, 1), else_=0)).label('has_state'),
            func.sum(func.case((OpportunityChain.base_contact_email != None, 1), else_=0)).label('has_contact')
        ).filter(
            OpportunityChain.solicitation_number.in_(processed_sols)
        ).first()
        
        if metadata_stats:
            print(f"   Agency: {metadata_stats.has_agency}/{total_processed} ({metadata_stats.has_agency/total_processed*100:.1f}%)")
            print(f"   NAICS: {metadata_stats.has_naics}/{total_processed} ({metadata_stats.has_naics/total_processed*100:.1f}%)")
            print(f"   State: {metadata_stats.has_state}/{total_processed} ({metadata_stats.has_state/total_processed*100:.1f}%)")
            print(f"   Contact: {metadata_stats.has_contact}/{total_processed} ({metadata_stats.has_contact/total_processed*100:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Build Contract Truth Layer")
    parser.add_argument('csv_file', help="Path to ContractOpportunitiesFullCSV.csv")
    parser.add_argument('--quiet', action='store_true', help="Suppress output")
    parser.add_argument('--limit', type=int, default=None, help="Process only first N solicitations (for testing)")
    
    args = parser.parse_args()
    
    db = SessionLocal()
    
    try:
        build_truth_table(args.csv_file, db, verbose=not args.quiet, limit=args.limit)
    finally:
        db.close()


if __name__ == "__main__":
    main()