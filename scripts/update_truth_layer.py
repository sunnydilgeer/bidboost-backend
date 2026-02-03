"""
Incremental Truth Layer Updater (UPSERT-based)
Evolved from: build_contract_truth.py

KEY CHANGES:
- Uses UPSERT (INSERT ... ON CONFLICT UPDATE) instead of INSERT-only
- PRESERVES existing pinecone_id and scraped_at fields (critical!)
- Processes daily CSV (500-2K rows) instead of full CSV (1M+ rows)
- Updates existing chains without losing enrichment data

Usage:
    python scripts/update_truth_layer.py data/daily/contracts_2026-02-02.csv
    python scripts/update_truth_layer.py data/daily/contracts_2026-02-02.csv --limit 100
"""

import csv
import re
import argparse
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models.company import OpportunityChain


# Amendment detection keywords (same as original)
AMENDMENT_KEYWORDS = [
    'amendment', 'amend', 'modification', 'mod ', 'mod-', 'revised', 
    'see attached', 'see attachment', 'addendum', 'cancellation',
    'cancel', 'updated', 'correction', 'change order'
]

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
    """Find the base notice from a group of related notices (same as original)."""
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
    
    good_ones = [s for s in scored if s['quality'] == 'GOOD']
    
    if good_ones:
        non_amendments = [s for s in good_ones if not s['is_amendment']]
        if non_amendments:
            good_ones = non_amendments
        
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
    
    for base_type in BASE_TYPES_PRIORITY:
        type_matches = [s for s in scored if s['notice'].get('BaseType') == base_type]
        
        if not type_matches:
            continue
        
        non_amendments = [s for s in type_matches if not s['is_amendment']]
        
        if non_amendments:
            return max(non_amendments, key=lambda s: s['desc_length'])['notice']
        
        return max(type_matches, key=lambda s: s['desc_length'])['notice']
    
    return max(scored, key=lambda s: s['desc_length'])['notice']


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse SAM.gov date string to UTC timezone-aware datetime."""
    if not date_str:
        return None
    try:
        clean_str = date_str.split('.')[0].replace(' ', 'T')
        
        try:
            dt = datetime.fromisoformat(clean_str)
        except:
            dt = datetime.strptime(clean_str.split('T')[0], '%Y-%m-%d')
        
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


def upsert_truth_layer(csv_filepath: str, db: Session, verbose: bool = True, limit: Optional[int] = None):
    """
    Incremental upsert to opportunity_chains.
    
    KEY DIFFERENCE FROM build_contract_truth.py:
    - Uses UPSERT instead of checking existence + insert/update
    - PRESERVES pinecone_id and scraped_at fields (critical for pipeline!)
    - More efficient for daily updates
    """
    
    if verbose:
        print("=" * 70)
        print("INCREMENTAL TRUTH LAYER UPDATE (UPSERT)")
        print("=" * 70)
        print(f"📂 Input: {csv_filepath}")
        if limit:
            print(f"🔬 Test mode: Processing first {limit} solicitations")
        print()
    
    if verbose:
        print("📖 Grouping notices by solicitation number...")
    
    grouped_notices = read_csv_by_solicitation(csv_filepath)
    
    if verbose:
        print(f"   Found {len(grouped_notices)} unique solicitation numbers")
        print()
    
    if limit:
        grouped_notices = dict(list(grouped_notices.items())[:limit])
        if verbose:
            print(f"   Limited to first {len(grouped_notices)} solicitations")
            print()
    
    if verbose:
        print("🔨 Upserting to opportunity_chains (preserving pinecone_id, scraped_at)...")
    
    created_count = 0
    updated_count = 0
    needs_sow_count = 0
    
    for idx, (sol_num, notices) in enumerate(grouped_notices.items(), 1):
        base = find_base_notice(notices)
        
        description = clean_html(base.get('Description', ''))
        quality = assess_description_quality(description)
        needs_sow = quality != "GOOD"
        
        if needs_sow:
            needs_sow_count += 1
        
        closing_dates = [
            parse_date(n.get('ResponseDeadLine', ''))
            for n in notices
        ]
        valid_dates = [d for d in closing_dates if d is not None]
        latest_closing = max(valid_dates) if valid_dates else None
        
        # Extract metadata with truncation
        base_agency = (base.get('Sub-Tier', '') or '')[:255]
        base_office = (base.get('Office', '') or '')[:500]
        base_naics = (base.get('NaicsCode', '') or '')[:10]
        base_psc = (base.get('ClassificationCode', '') or '')[:10]
        base_set_aside = (base.get('SetASide', '') or '')[:100]
        base_state = (base.get('PopState', '') or '')[:50]
        base_city = (base.get('PopCity', '') or '')[:100]
        base_contact_name = (base.get('PrimaryContactFullname', '') or '')[:200]
        base_contact_email = (base.get('PrimaryContactEmail', '') or '')[:200]
        base_contact_phone = (base.get('PrimaryContactPhone', '') or '')[:50]

        # ✅ CRITICAL: UPSERT with field preservation
        stmt = insert(OpportunityChain).values(
            solicitation_number=sol_num,
            base_notice_id=base.get('NoticeId', ''),
            base_sol_number=base.get('Sol#', ''),
            base_description=description,
            base_posted_date=parse_date(base.get('PostedDate', '')),
            base_type=base.get('BaseType', ''),
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
            needs_sow_extraction=needs_sow,
            updated_at=datetime.now(timezone.utc)
        ).on_conflict_do_update(
            index_elements=['solicitation_number'],
            set_={
                'base_notice_id': base.get('NoticeId', ''),
                'base_sol_number': base.get('Sol#', ''),
                'base_description': description,
                'base_posted_date': parse_date(base.get('PostedDate', '')),
                'base_type': base.get('BaseType', ''),
                'base_agency': base_agency,
                'base_office': base_office,
                'base_naics': base_naics,
                'base_psc': base_psc,
                'base_set_aside': base_set_aside,
                'base_state': base_state,
                'base_city': base_city,
                'base_contact_name': base_contact_name,
                'base_contact_email': base_contact_email,
                'base_contact_phone': base_contact_phone,
                'notice_count': len(notices),
                'has_amendments': len(notices) > 1,
                'latest_closing_date': latest_closing,
                'base_description_quality': quality,
                'needs_sow_extraction': needs_sow,
                'updated_at': datetime.now(timezone.utc)
                # ✅ CRITICAL: pinecone_id and scraped_at are NOT in set_ - they're preserved!
            }
        )
        
        result = db.execute(stmt)
        
        # Track if this was insert or update (PostgreSQL returns rowcount)
        if result.rowcount > 0:
            # Check if existing record to determine created vs updated
            existing = db.query(OpportunityChain).filter_by(solicitation_number=sol_num).first()
            if existing.created_at < datetime.now(timezone.utc).replace(hour=0, minute=0):
                updated_count += 1
            else:
                created_count += 1
        
        if verbose and idx % 100 == 0:
            print(f"   Processed {idx:,} / {len(grouped_notices):,} chains...")
        
        if idx % 1000 == 0:
            db.commit()
    
    db.commit()
    
    if verbose:
        print()
        print("=" * 70)
        print("✅ INCREMENTAL UPDATE COMPLETE")
        print("=" * 70)
        print(f"   Created: {created_count} new chains")
        print(f"   Updated: {updated_count} existing chains")
        print(f"   Total processed: {created_count + updated_count}")
        print()
        print(f"🔍 Needs SOW extraction: {needs_sow_count} contracts")
        print()
        print("⚠️  PRESERVED FIELDS:")
        print("   - pinecone_id (not overwritten)")
        print("   - scraped_at (not overwritten)")


def main():
    parser = argparse.ArgumentParser(description="Incremental Truth Layer Update (UPSERT)")
    parser.add_argument('csv_file', help="Path to daily CSV (e.g., data/daily/contracts_2026-02-02.csv)")
    parser.add_argument('--quiet', action='store_true', help="Suppress output")
    parser.add_argument('--limit', type=int, default=None, help="Process only first N solicitations (for testing)")
    
    args = parser.parse_args()
    
    db = SessionLocal()
    
    try:
        upsert_truth_layer(args.csv_file, db, verbose=not args.quiet, limit=args.limit)
    finally:
        db.close()


if __name__ == "__main__":
    main()