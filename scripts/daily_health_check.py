"""
Daily Health Check for Contract Pipeline
Evolved from: track_truth_quality.py

Checks:
- Data quality metrics
- Embedding coverage
- Scraping progress
- Pipeline freshness

Returns exit code 0 (success) or 1 (failure) for automation.

Usage:
    python scripts/daily_health_check.py
    python scripts/daily_health_check.py --verbose
"""

import argparse
import sys
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from app.database import SessionLocal
from app.models.company import OpportunityChain


def main():
    parser = argparse.ArgumentParser(description="Daily pipeline health check")
    parser.add_argument('--verbose', action='store_true', help="Show detailed stats")
    args = parser.parse_args()
    
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    
    print("=" * 70)
    print("DAILY PIPELINE HEALTH CHECK")
    print("=" * 70)
    print(f"🕐 Generated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    # Track issues
    issues = []
    
    # ============================================================
    # CHECK 1: LIVE OPPORTUNITIES
    # ============================================================
    live_query = db.query(OpportunityChain).filter(
        OpportunityChain.latest_closing_date >= now
    )
    
    total_live = live_query.count()
    
    if total_live == 0:
        issues.append("No live opportunities found")
    
    print(f"📊 LIVE Opportunities: {total_live:,}")
    print()
    
    # ============================================================
    # CHECK 2: QUALITY BREAKDOWN
    # ============================================================
    quality_stats = db.query(
        OpportunityChain.base_description_quality,
        func.count(OpportunityChain.id)
    ).filter(
        OpportunityChain.latest_closing_date >= now
    ).group_by(OpportunityChain.base_description_quality).all()
    
    quality_dict = dict(quality_stats)
    good_count = quality_dict.get('GOOD', 0)
    good_pct = (good_count / total_live * 100) if total_live > 0 else 0
    
    if good_pct < 50:
        issues.append(f"GOOD quality too low: {good_pct:.1f}% (expected >50%)")
    
    if args.verbose:
        print("Quality Breakdown:")
        for quality, count in sorted(quality_stats, key=lambda x: x[1], reverse=True):
            pct = (count / total_live * 100) if total_live > 0 else 0
            print(f"   {quality:8s}: {count:4d} ({pct:5.1f}%)")
        print()
    else:
        print(f"✅ GOOD quality: {good_count:,} ({good_pct:.1f}%)")
        print()
    
    # ============================================================
    # CHECK 3: EMBEDDING COVERAGE
    # ============================================================
    embedded_count = live_query.filter(
        OpportunityChain.pinecone_id.isnot(None),
        OpportunityChain.base_description_quality == 'GOOD'
    ).count()
    
    good_live = live_query.filter(
        OpportunityChain.base_description_quality == 'GOOD'
    ).count()
    
    embedding_coverage = (embedded_count / good_live * 100) if good_live > 0 else 0
    
    if embedding_coverage < 95:
        issues.append(f"Embedding coverage too low: {embedding_coverage:.1f}% (expected >95%)")
    
    print(f"🔌 Embedding Coverage:")
    print(f"   Embedded: {embedded_count:,} / {good_live:,} GOOD contracts")
    print(f"   Coverage: {embedding_coverage:.1f}%")
    print()
    
    # ============================================================
    # CHECK 4: DATA FRESHNESS
    # ============================================================
    yesterday = now - timedelta(days=1)
    recent_updates = db.query(OpportunityChain).filter(
        OpportunityChain.updated_at >= yesterday
    ).count()
    
    if recent_updates == 0:
        issues.append("No updates in last 24 hours - pipeline may be stale")
    
    print(f"🕐 Data Freshness:")
    print(f"   Updated in last 24h: {recent_updates:,}")
    print()
    
    # ============================================================
    # CHECK 5: SCRAPING PROGRESS (Optional)
    # ============================================================
    if args.verbose:
        scraped = live_query.filter(
            OpportunityChain.scraped_at.isnot(None)
        ).count()
        
        remaining_poor = live_query.filter(
            OpportunityChain.base_description_quality.in_(['POOR', 'MISSING']),
            OpportunityChain.scraped_at.is_(None)
        ).count()
        
        print(f"🔍 Scraping Progress:")
        print(f"   Scraped: {scraped:,}")
        print(f"   Remaining POOR/MISSING: {remaining_poor:,}")
        print()
    
    # ============================================================
    # FINAL VERDICT
    # ============================================================
    print("=" * 70)
    
    if len(issues) == 0:
        print("✅ HEALTH CHECK PASSED")
        print("=" * 70)
        db.close()
        sys.exit(0)
    else:
        print("❌ HEALTH CHECK FAILED")
        print("=" * 70)
        print()
        print("Issues found:")
        for issue in issues:
            print(f"   - {issue}")
        print()
        db.close()
        sys.exit(1)


if __name__ == "__main__":
    main()