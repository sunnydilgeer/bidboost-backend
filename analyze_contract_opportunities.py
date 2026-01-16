"""
Analyze ContractOpportunitiesFullCSV.csv to understand the full dataset
Shows what opportunities are available and what we should ingest
"""

import csv
from datetime import datetime
from collections import Counter
from pathlib import Path

CSV_FILE = Path("./data/ContractOpportunitiesFullCSV.csv")


def parse_deadline(date_str: str):
    """Parse deadline to check if it's still open."""
    if not date_str:
        return None
    
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d",
    ]
    
    for fmt in formats:
        try:
            # Remove timezone name if present (e.g., "-05:00" or "EST")
            cleaned = date_str.strip().split()[0]
            return datetime.strptime(cleaned, fmt.replace("%z", ""))
        except (ValueError, IndexError):
            continue
    return None


def analyze_csv():
    print("=" * 70)
    print("CONTRACT OPPORTUNITIES FULL CSV ANALYSIS")
    print("=" * 70)
    print()
    
    total_rows = 0
    by_type = Counter()
    by_base_type = Counter()
    by_active = Counter()
    by_archive_type = Counter()
    
    with_award = 0
    with_opp_id = 0
    with_sol_number = 0
    with_description = 0
    with_deadline = 0
    open_deadline = 0
    closed_deadline = 0
    with_naics = 0
    
    active_solicitations = 0
    active_with_open_deadline = 0
    
    now = datetime.now()
    
    solicitation_types = set()
    
    print("📖 Reading CSV... (this may take a minute)")
    
    with open(CSV_FILE, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            total_rows += 1
            
            # Extract fields
            opp_id = row.get("NoticeId", "").strip()
            sol_number = row.get("Sol#", "").strip()
            opp_type = row.get("Type", "").strip()
            base_type = row.get("BaseType", "").strip()
            active = row.get("Active", "").strip().lower()
            archive_type = row.get("ArchiveType", "").strip()
            award_number = row.get("AwardNumber", "").strip()
            description = row.get("Description", "").strip()
            deadline_str = row.get("ResponseDeadLine", "").strip()
            naics = row.get("NaicsCode", "").strip()
            
            # Count fields
            by_type[opp_type] += 1
            by_base_type[base_type] += 1
            by_active[active] += 1
            by_archive_type[archive_type if archive_type else "No Archive Type"] += 1
            
            if opp_id:
                with_opp_id += 1
            if sol_number:
                with_sol_number += 1
            if description:
                with_description += 1
            if award_number:
                with_award += 1
            if naics:
                with_naics += 1
            
            # Deadline analysis
            if deadline_str:
                with_deadline += 1
                deadline = parse_deadline(deadline_str)
                if deadline:
                    if deadline > now:
                        open_deadline += 1
                    else:
                        closed_deadline += 1
            
            # Track active solicitations (what you actually want)
            if active == "yes":
                # These are the biddable types
                if base_type in ["Solicitation", "Combined Synopsis/Solicitation"]:
                    solicitation_types.add(opp_type)
                    active_solicitations += 1
                    
                    # Check if deadline is open
                    deadline = parse_deadline(deadline_str)
                    if deadline and deadline > now:
                        active_with_open_deadline += 1
            
            # Progress indicator
            if total_rows % 10000 == 0:
                print(f"  Processed {total_rows:,} rows...")
    
    print()
    print("=" * 70)
    print(f"📊 TOTAL ROWS: {total_rows:,}")
    print("=" * 70)
    print()
    
    print("📋 BY TYPE (Top 10):")
    for opp_type, count in by_type.most_common(10):
        pct = (count / total_rows * 100)
        print(f"  {opp_type}: {count:,} ({pct:.1f}%)")
    print()
    
    print("📋 BY BASE TYPE:")
    for base_type, count in by_base_type.most_common():
        pct = (count / total_rows * 100)
        print(f"  {base_type}: {count:,} ({pct:.1f}%)")
    print()
    
    print("📊 BY ACTIVE STATUS:")
    for status, count in by_active.most_common():
        pct = (count / total_rows * 100)
        print(f"  {status}: {count:,} ({pct:.1f}%)")
    print()
    
    print("📦 BY ARCHIVE TYPE (Top 5):")
    for archive, count in list(by_archive_type.most_common())[:5]:
        pct = (count / total_rows * 100)
        print(f"  {archive}: {count:,} ({pct:.1f}%)")
    print()
    
    print("=" * 70)
    print("DATA COMPLETENESS")
    print("=" * 70)
    print(f"With NoticeId (OPP_ID): {with_opp_id:,} ({with_opp_id/total_rows*100:.1f}%)")
    print(f"With Sol# (Solicitation Number): {with_sol_number:,} ({with_sol_number/total_rows*100:.1f}%)")
    print(f"With Description: {with_description:,} ({with_description/total_rows*100:.1f}%)")
    print(f"With NAICS Code: {with_naics:,} ({with_naics/total_rows*100:.1f}%)")
    print(f"With Response Deadline: {with_deadline:,} ({with_deadline/total_rows*100:.1f}%)")
    print(f"With Award Number: {with_award:,} ({with_award/total_rows*100:.1f}%)")
    print()
    
    print("=" * 70)
    print("DEADLINE ANALYSIS")
    print("=" * 70)
    print(f"Total with deadlines: {with_deadline:,}")
    print(f"  ✅ Open (future): {open_deadline:,} ({open_deadline/with_deadline*100:.1f}%)")
    print(f"  ⏰ Closed (past): {closed_deadline:,} ({closed_deadline/with_deadline*100:.1f}%)")
    print()
    
    print("=" * 70)
    print("BIDDABLE OPPORTUNITIES (Active Solicitations)")
    print("=" * 70)
    print(f"Active = 'Yes' + BaseType = 'Solicitation/Combined': {active_solicitations:,}")
    print(f"  ✅ With OPEN deadline: {active_with_open_deadline:,}")
    print(f"  ⏰ With CLOSED/No deadline: {active_solicitations - active_with_open_deadline:,}")
    print()
    
    print("Solicitation Type breakdown:")
    for sol_type in sorted(solicitation_types):
        count = by_type[sol_type]
        print(f"  {sol_type}: {count:,}")
    print()
    
    print("=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)
    print(f"✅ INGEST: Active solicitations with OPEN deadlines = {active_with_open_deadline:,}")
    print(f"📋 OPTIONAL: Include presolicitations/sources sought")
    print(f"❌ EXCLUDE: Awards ({with_award:,}), closed deadlines, inactive")
    print()
    print(f"🎯 TARGET: ~{active_with_open_deadline:,} opportunities")
    print(f"   (vs current 853 from contract_notice_details.csv)")
    print("=" * 70)


if __name__ == "__main__":
    analyze_csv()