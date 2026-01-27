"""
Track Contract Truth Layer Quality
Shows quality metrics for LIVE opportunities

Usage:
    python track_truth_quality.py
"""

from datetime import datetime, timezone
from sqlalchemy import func
from app.database import SessionLocal
from app.models.company import OpportunityChain


def main():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    
    print("=" * 70)
    print("CONTRACT TRUTH LAYER QUALITY REPORT")
    print("=" * 70)
    print(f"🕐 Generated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    # LIVE opportunities only
    live_query = db.query(OpportunityChain).filter(
        OpportunityChain.latest_closing_date >= now
    )
    
    total_live = live_query.count()
    
    # Quality breakdown
    quality_stats = db.query(
        OpportunityChain.base_description_quality,
        func.count(OpportunityChain.id)
    ).filter(
        OpportunityChain.latest_closing_date >= now
    ).group_by(OpportunityChain.base_description_quality).all()
    
    print(f"📊 LIVE Opportunities: {total_live:,}")
    print()
    print("Quality Breakdown:")
    for quality, count in sorted(quality_stats, key=lambda x: x[1], reverse=True):
        pct = (count / total_live * 100) if total_live > 0 else 0
        print(f"   {quality:8s}: {count:4d} ({pct:5.1f}%)")
    
    print()
    
    # Scraping progress
    scraped = live_query.filter(
        OpportunityChain.attachments_fetched_at != None
    ).count()
    
    not_scraped = live_query.filter(
        OpportunityChain.attachments_fetched_at == None
    ).count()
    
    print("Scraping Progress:")
    print(f"   Scraped:     {scraped:4d}")
    print(f"   Not scraped: {not_scraped:4d}")
    
    if total_live > 0:
        scraped_pct = (scraped / total_live * 100)
        print(f"   Progress:    {scraped_pct:.1f}%")
    
    print()
    
    # Remaining work
    remaining_poor = live_query.filter(
        OpportunityChain.base_description_quality.in_(['POOR', 'MISSING']),
        OpportunityChain.attachments_fetched_at == None
    ).count()
    
    print(f"🔍 Remaining POOR/MISSING to scrape: {remaining_poor}")
    
    if remaining_poor > 0:
        days_at_200 = remaining_poor / 200
        print(f"   At 200/day: ~{days_at_200:.0f} days to complete")
    
    print()
    print("=" * 70)
    
    db.close()


if __name__ == "__main__":
    main()