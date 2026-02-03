"""
Identify contracts needing scraping/enrichment.
Prioritizes by closing date and missing fields.

Usage:
    python scripts/identify_poor_contracts.py
    python scripts/identify_poor_contracts.py --limit 1000
    python scripts/identify_poor_contracts.py --output data/to_scrape.csv
"""

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from app.database import SessionLocal
from app.models.company import OpportunityChain


def identify_poor_contracts(limit: int = 1000, output_path: str = "data/to_scrape.csv"):
    """
    Identify contracts needing scraping.
    
    Priority criteria:
    1. POOR/MISSING quality descriptions
    2. Still open (closing_date >= today)
    3. NOT already scraped (scraped_at IS NULL)
    4. Sort by closing date (urgent first)
    """
    
    print("=" * 70)
    print("IDENTIFY CONTRACTS NEEDING SCRAPING")
    print("=" * 70)
    print(f"📊 Limit: {limit} contracts")
    print(f"📁 Output: {output_path}")
    print()
    
    db = SessionLocal()
    
    # Query poor quality contracts
    print("🔍 Finding contracts needing enrichment...")
    
    contracts = db.query(OpportunityChain).filter(
        # Poor quality
        OpportunityChain.base_description_quality.in_(['POOR', 'MISSING']),
        # Still open
        OpportunityChain.latest_closing_date >= datetime.now(timezone.utc),
        # Not already scraped
        OpportunityChain.scraped_at.is_(None),
        # Not award notices
        OpportunityChain.base_type.notin_(['Award Notice', 'Justification'])
    ).order_by(
        # Closing soon = high priority
        OpportunityChain.latest_closing_date.asc(),
        OpportunityChain.base_posted_date.desc()
    ).limit(limit).all()
    
    print(f"   Found {len(contracts)} contracts needing scraping")
    print()
    
    if len(contracts) == 0:
        print("✅ No contracts need scraping!")
        db.close()
        return
    
    # Stats
    poor_count = sum(1 for c in contracts if c.base_description_quality == 'POOR')
    missing_count = sum(1 for c in contracts if c.base_description_quality == 'MISSING')
    
    print(f"📊 Quality breakdown:")
    print(f"   POOR: {poor_count}")
    print(f"   MISSING: {missing_count}")
    print()
    
    # Write to CSV
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'solicitation_number',
            'base_notice_id',
            'source_url',
            'closing_date',
            'quality',
            'priority'
        ])
        
        for idx, contract in enumerate(contracts, 1):
            # Calculate priority (1 = highest)
            days_until_close = (contract.latest_closing_date - datetime.now(timezone.utc)).days
            
            if days_until_close <= 7:
                priority = 1  # Urgent
            elif days_until_close <= 14:
                priority = 2  # High
            elif days_until_close <= 30:
                priority = 3  # Medium
            else:
                priority = 4  # Low
            
            writer.writerow([
                contract.solicitation_number,
                contract.base_notice_id,
                f"https://sam.gov/opp/{contract.base_notice_id}/view",
                contract.latest_closing_date.isoformat() if contract.latest_closing_date else '',
                contract.base_description_quality,
                priority
            ])
    
    print("=" * 70)
    print("✅ IDENTIFICATION COMPLETE")
    print("=" * 70)
    print(f"   Contracts to scrape: {len(contracts)}")
    print(f"   Output file: {output_path}")
    print()
    print(f"📅 Priority breakdown:")
    priority_counts = {}
    for c in contracts:
        days = (c.latest_closing_date - datetime.now(timezone.utc)).days
        if days <= 7:
            priority_counts[1] = priority_counts.get(1, 0) + 1
        elif days <= 14:
            priority_counts[2] = priority_counts.get(2, 0) + 1
        elif days <= 30:
            priority_counts[3] = priority_counts.get(3, 0) + 1
        else:
            priority_counts[4] = priority_counts.get(4, 0) + 1
    
    print(f"   Priority 1 (≤7 days): {priority_counts.get(1, 0)}")
    print(f"   Priority 2 (≤14 days): {priority_counts.get(2, 0)}")
    print(f"   Priority 3 (≤30 days): {priority_counts.get(3, 0)}")
    print(f"   Priority 4 (>30 days): {priority_counts.get(4, 0)}")
    
    db.close()


def main():
    parser = argparse.ArgumentParser(description="Identify contracts needing scraping")
    parser.add_argument('--limit', type=int, default=1000, help="Max contracts to identify")
    parser.add_argument('--output', type=str, default='data/to_scrape.csv', help="Output CSV path")
    
    args = parser.parse_args()
    
    identify_poor_contracts(limit=args.limit, output_path=args.output)


if __name__ == "__main__":
    main()