"""
Deep dive analysis of opportunities with no response deadline
Understand what these 31k+ opportunities actually are
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

CSV_FILE = Path("./data/ContractOpportunitiesFullCSV.csv")


def parse_date(date_str: str):
    """Parse various date formats."""
    if not date_str:
        return None
    
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
    ]
    
    for fmt in formats:
        try:
            # Remove timezone info for simple parsing
            cleaned = date_str.strip().split('.')[0].split('+')[0].split('-')[0:3]
            cleaned = '-'.join(cleaned)
            return datetime.strptime(cleaned, "%Y-%m-%d")
        except (ValueError, IndexError):
            continue
    return None


def analyze_no_deadline():
    print("=" * 70)
    print("NO DEADLINE OPPORTUNITIES - DEEP ANALYSIS")
    print("=" * 70)
    print()
    
    total_biddable = 0
    no_deadline_count = 0
    
    # Counters for no-deadline opps
    by_type = Counter()
    by_base_type = Counter()
    by_archive_type = Counter()
    has_award = 0
    has_archive_date = 0
    
    # Posted date analysis
    posted_dates = []
    archive_dates = []
    
    # How old are they?
    posted_within_30d = 0
    posted_within_90d = 0
    posted_within_180d = 0
    posted_over_180d = 0
    
    # Sample records
    samples = []
    
    now = datetime.now()
    
    print("📖 Reading CSV...")
    
    with open(CSV_FILE, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            base_type = row.get("BaseType", "").strip()
            active = row.get("Active", "").strip().lower()
            deadline_str = row.get("ResponseDeadLine", "").strip()
            
            # Check if biddable
            is_biddable = (base_type in ["Solicitation", "Combined Synopsis/Solicitation"] and 
                          active == "yes")
            
            if not is_biddable:
                continue
            
            total_biddable += 1
            
            # Focus on no-deadline opportunities
            if not deadline_str:
                no_deadline_count += 1
                
                # Type analysis
                opp_type = row.get("Type", "").strip()
                by_type[opp_type] += 1
                by_base_type[base_type] += 1
                
                # Archive info
                archive_type = row.get("ArchiveType", "").strip()
                archive_date_str = row.get("ArchiveDate", "").strip()
                by_archive_type[archive_type if archive_type else "No Archive Type"] += 1
                
                if archive_date_str:
                    has_archive_date += 1
                    archive_date = parse_date(archive_date_str)
                    if archive_date:
                        archive_dates.append(archive_date)
                
                # Award info
                award_number = row.get("AwardNumber", "").strip()
                if award_number:
                    has_award += 1
                
                # Posted date analysis
                posted_date_str = row.get("PostedDate", "").strip()
                posted_date = parse_date(posted_date_str)
                
                if posted_date:
                    posted_dates.append(posted_date)
                    days_ago = (now - posted_date).days
                    
                    if days_ago <= 30:
                        posted_within_30d += 1
                    elif days_ago <= 90:
                        posted_within_90d += 1
                    elif days_ago <= 180:
                        posted_within_180d += 1
                    else:
                        posted_over_180d += 1
                
                # Collect samples (first 10)
                if len(samples) < 10:
                    samples.append({
                        "Notice ID": row.get("Sol#", ""),
                        "Title": row.get("Title", "")[:60],
                        "Type": opp_type,
                        "Posted": posted_date_str[:10] if posted_date_str else "Unknown",
                        "Archive Date": archive_date_str[:10] if archive_date_str else "None",
                        "Archive Type": archive_type if archive_type else "None",
                        "Award": "Yes" if award_number else "No",
                    })
    
    print()
    print("=" * 70)
    print(f"📊 TOTAL BIDDABLE: {total_biddable:,}")
    print(f"❓ NO DEADLINE: {no_deadline_count:,} ({no_deadline_count/total_biddable*100:.1f}%)")
    print("=" * 70)
    print()
    
    # Type breakdown
    print("📋 BY OPPORTUNITY TYPE:")
    for opp_type, count in by_type.most_common():
        pct = (count / no_deadline_count * 100) if no_deadline_count > 0 else 0
        print(f"  {opp_type:50} {count:>6,} ({pct:>5.1f}%)")
    print()
    
    print("📋 BY BASE TYPE:")
    for base_type, count in by_base_type.most_common():
        pct = (count / no_deadline_count * 100) if no_deadline_count > 0 else 0
        print(f"  {base_type:50} {count:>6,} ({pct:>5.1f}%)")
    print()
    
    # Archive analysis
    print("📦 ARCHIVE INFORMATION:")
    print(f"  Has Archive Date: {has_archive_date:,} ({has_archive_date/no_deadline_count*100:.1f}%)")
    print()
    print("  Archive Types:")
    for archive_type, count in by_archive_type.most_common():
        pct = (count / no_deadline_count * 100) if no_deadline_count > 0 else 0
        print(f"    {archive_type:40} {count:>6,} ({pct:>5.1f}%)")
    print()
    
    # Award status
    print("💰 AWARD STATUS:")
    print(f"  Has Award Number: {has_award:,} ({has_award/no_deadline_count*100:.1f}%)")
    print(f"  No Award: {no_deadline_count - has_award:,} ({(no_deadline_count-has_award)/no_deadline_count*100:.1f}%)")
    print()
    
    # Age analysis
    print("📅 AGE ANALYSIS (When Posted):")
    print(f"  Within 30 days: {posted_within_30d:,} ({posted_within_30d/no_deadline_count*100:.1f}%)")
    print(f"  31-90 days ago: {posted_within_90d:,} ({posted_within_90d/no_deadline_count*100:.1f}%)")
    print(f"  91-180 days ago: {posted_within_180d:,} ({posted_within_180d/no_deadline_count*100:.1f}%)")
    print(f"  Over 180 days ago: {posted_over_180d:,} ({posted_over_180d/no_deadline_count*100:.1f}%)")
    print()
    
    # Posted date statistics
    if posted_dates:
        oldest = min(posted_dates)
        newest = max(posted_dates)
        print(f"  Oldest posted: {oldest.strftime('%Y-%m-%d')} ({(now - oldest).days} days ago)")
        print(f"  Newest posted: {newest.strftime('%Y-%m-%d')} ({(now - newest).days} days ago)")
        print()
    
    # Archive date statistics
    if archive_dates:
        print("📆 ARCHIVE DATE ANALYSIS:")
        future_archives = [d for d in archive_dates if d > now]
        past_archives = [d for d in archive_dates if d <= now]
        
        print(f"  Future archive dates: {len(future_archives):,}")
        print(f"  Past archive dates: {len(past_archives):,}")
        
        if future_archives:
            nearest_archive = min(future_archives)
            print(f"  Nearest archive: {nearest_archive.strftime('%Y-%m-%d')} (in {(nearest_archive - now).days} days)")
        
        if past_archives:
            most_recent_past = max(past_archives)
            print(f"  Most recent past archive: {most_recent_past.strftime('%Y-%m-%d')} ({(now - most_recent_past).days} days ago)")
        print()
    
    # Sample records
    print("=" * 70)
    print("SAMPLE RECORDS (First 10):")
    print("=" * 70)
    for i, sample in enumerate(samples, 1):
        print(f"\n{i}. {sample['Title']}")
        print(f"   Notice ID: {sample['Notice ID']}")
        print(f"   Type: {sample['Type']}")
        print(f"   Posted: {sample['Posted']}")
        print(f"   Archive Date: {sample['Archive Date']}")
        print(f"   Archive Type: {sample['Archive Type']}")
        print(f"   Has Award: {sample['Award']}")
    
    print()
    print("=" * 70)
    print("RECOMMENDATION:")
    print("=" * 70)
    
    if has_award / no_deadline_count > 0.5:
        print("⚠️  MAJORITY HAVE AWARDS - These appear to be closed/completed")
    elif posted_over_180d / no_deadline_count > 0.5:
        print("⚠️  MAJORITY ARE OLD - These may be stale/inactive")
    elif posted_within_30d / no_deadline_count > 0.3:
        print("✅ MANY ARE RECENT - These may be valid opportunities without formal deadlines")
    else:
        print("❓ MIXED - Further investigation needed")
    
    print("=" * 70)


if __name__ == "__main__":
    analyze_no_deadline()