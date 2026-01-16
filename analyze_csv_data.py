"""
Analyze contract_notice_details.csv to understand filtering
Shows what's being excluded and why
"""

import csv
from datetime import datetime
from collections import Counter
from pathlib import Path

CSV_FILE = Path("./data/contract_notice_details.csv")

# From your ingestion script
BIDDABLE_TYPES = {
    "Combined Synopsis/Solicitation",
    "Solicitation",
}

PIPELINE_TYPES = {
    "Presolicitation",
    "Sources Sought",
}


def parse_deadline(date_str: str):
    """Parse deadline to check if it's still open."""
    if not date_str:
        return None
    
    formats = [
        "%b %d, %Y %I:%M %p UTC",
        "%b %d, %Y %H:%M %p UTC",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def analyze_csv():
    print("=" * 70)
    print("CONTRACT CSV DATA ANALYSIS")
    print("=" * 70)
    print()
    
    total_rows = 0
    by_type = Counter()
    by_status = Counter()
    biddable_count = 0
    pipeline_count = 0
    active_biddable = 0
    active_with_open_deadline = 0
    closed_deadline = 0
    no_deadline = 0
    
    now = datetime.now()
    
    with open(CSV_FILE, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            total_rows += 1
            
            opp_type = row.get("Contract Opportunity Type", "").strip()
            status = row.get("Status", "").strip().lower()
            notice_id = row.get("Notice ID", "").strip()
            deadline_str = row.get("Current Response Date", "").strip()
            
            by_type[opp_type] += 1
            by_status[status] += 1
            
            # Check if biddable
            if opp_type in BIDDABLE_TYPES:
                biddable_count += 1
                
                if status == "active":
                    active_biddable += 1
                    
                    # Check deadline
                    deadline = parse_deadline(deadline_str)
                    if deadline:
                        if deadline > now:
                            active_with_open_deadline += 1
                        else:
                            closed_deadline += 1
                    else:
                        no_deadline += 1
            
            # Check if pipeline
            if opp_type in PIPELINE_TYPES:
                pipeline_count += 1
    
    # Report
    print(f"📊 TOTAL ROWS: {total_rows:,}")
    print()
    
    print("📋 BY OPPORTUNITY TYPE:")
    for opp_type, count in by_type.most_common():
        pct = (count / total_rows * 100)
        marker = "✅" if opp_type in BIDDABLE_TYPES else "📋" if opp_type in PIPELINE_TYPES else "❌"
        print(f"  {marker} {opp_type}: {count:,} ({pct:.1f}%)")
    print()
    
    print("📊 BY STATUS:")
    for status, count in by_status.most_common():
        pct = (count / total_rows * 100)
        print(f"  {status}: {count:,} ({pct:.1f}%)")
    print()
    
    print("=" * 70)
    print("FILTERING BREAKDOWN")
    print("=" * 70)
    print(f"Total opportunities: {total_rows:,}")
    print(f"  ✅ Biddable types (Solicitation + Combined Synopsis): {biddable_count:,}")
    print(f"  📋 Pipeline types (Presolicitation + Sources Sought): {pipeline_count:,}")
    print(f"  ❌ Other types (Awards, Notices, etc.): {total_rows - biddable_count - pipeline_count:,}")
    print()
    print(f"Biddable + Active status: {active_biddable:,}")
    print(f"  ✅ With open deadline (future): {active_with_open_deadline:,}")
    print(f"  ⏰ With closed deadline (past): {closed_deadline:,}")
    print(f"  ❓ No deadline info: {no_deadline:,}")
    print()
    
    print("=" * 70)
    print("CURRENT INGESTION LOGIC")
    print("=" * 70)
    print(f"Currently ingesting: {active_biddable:,} opportunities")
    print(f"  (Biddable types + Active status only)")
    print()
    print("TO GET 20K+ OPPORTUNITIES, YOU COULD:")
    print(f"  1. Include Pipeline types → Would add {pipeline_count:,} more")
    print(f"  2. Include expired deadlines → Would keep all {active_biddable:,}")
    print(f"  3. Check if CSV is filtered → SAM.gov export settings")
    print()


if __name__ == "__main__":
    analyze_csv()