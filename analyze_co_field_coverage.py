"""
Analyze ContractOpportunitiesFullCSV.csv field coverage
Shows what percentage of records have the fields needed for the platform
"""

import csv
from datetime import datetime
from pathlib import Path
from collections import Counter

CSV_FILE = Path("./data/ContractOpportunitiesFullCSV.csv")


def parse_deadline(date_str: str):
    """Parse deadline - simple YYYY-MM-DD format."""
    if not date_str:
        return None
    
    try:
        # ResponseDeadLine is just YYYY-MM-DD
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def analyze_coverage():
    print("=" * 70)
    print("CONTRACT OPPORTUNITIES CSV - FIELD COVERAGE ANALYSIS")
    print("=" * 70)
    print()
    
    # Platform fields to check
    fields_to_check = {
        "NoticeId": "OPP_ID (for SAM.gov links)",
        "Sol#": "Notice/Solicitation Number",
        "Title": "Opportunity Title",
        "Department/Ind.Agency": "Agency/Department",
        "Sub-Tier": "Sub-Agency",
        "NaicsCode": "NAICS Code",
        "ClassificationCode": "PSC Code",
        "SetASide": "Set-Aside Type",  # FIXED: Capital A
        "Description": "Description",
        "PostedDate": "Posted Date",
        "ResponseDeadLine": "Response Deadline",
        "AwardNumber": "Award Number",
        "Award$": "Award Amount",
        "PrimaryContactFullname": "Primary Contact Name",
        "PrimaryContactEmail": "Primary Contact Email",
        "PrimaryContactPhone": "Primary Contact Phone",
    }
    
    total_rows = 0
    field_counts = {field: 0 for field in fields_to_check.keys()}
    field_non_empty = {field: 0 for field in fields_to_check.keys()}
    
    # For biddable opportunities only
    biddable_count = 0
    biddable_field_counts = {field: 0 for field in fields_to_check.keys()}
    
    open_deadline_count = 0
    open_field_counts = {field: 0 for field in fields_to_check.keys()}
    
    now = datetime.now()
    
    print("📖 Reading CSV... (this may take a minute)")
    
    with open(CSV_FILE, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            total_rows += 1
            
            # Check all fields
            for field in fields_to_check.keys():
                value = row.get(field, "").strip()
                if value:
                    field_counts[field] += 1
                    # Count non-trivial values (not just "null" or "N/A")
                    if value.lower() not in ["null", "n/a", "na", "none", ""]:
                        field_non_empty[field] += 1
            
            # Check for biddable opportunities (Solicitation + Combined Synopsis)
            base_type = row.get("BaseType", "").strip()
            active = row.get("Active", "").strip().lower()
            deadline_str = row.get("ResponseDeadLine", "").strip()
            
            is_biddable = (base_type in ["Solicitation", "Combined Synopsis/Solicitation"] and 
                          active == "yes")
            
            if is_biddable:
                biddable_count += 1
                for field in fields_to_check.keys():
                    value = row.get(field, "").strip()
                    if value and value.lower() not in ["null", "n/a", "na", "none", ""]:
                        biddable_field_counts[field] += 1
                
                # Check if deadline is open
                deadline = parse_deadline(deadline_str)
                if deadline and deadline > now:
                    open_deadline_count += 1
                    for field in fields_to_check.keys():
                        value = row.get(field, "").strip()
                        if value and value.lower() not in ["null", "n/a", "na", "none", ""]:
                            open_field_counts[field] += 1
            
            # Progress
            if total_rows % 10000 == 0:
                print(f"  Processed {total_rows:,} rows...")
    
    print()
    print("=" * 70)
    print(f"📊 TOTAL ROWS: {total_rows:,}")
    print(f"📋 BIDDABLE OPPORTUNITIES: {biddable_count:,}")
    print(f"✅ OPEN DEADLINE (biddable): {open_deadline_count:,}")
    print("=" * 70)
    print()
    
    # Overall coverage
    print("=" * 70)
    print("FIELD COVERAGE - ALL OPPORTUNITIES")
    print("=" * 70)
    for field, description in fields_to_check.items():
        count = field_non_empty[field]
        pct = (count / total_rows * 100) if total_rows > 0 else 0
        status = "✅" if pct >= 90 else "⚠️" if pct >= 70 else "❌"
        print(f"{status} {description:40} {count:>6,} / {total_rows:,} ({pct:>5.1f}%)")
    print()
    
    # Biddable opportunities coverage
    print("=" * 70)
    print("FIELD COVERAGE - BIDDABLE OPPORTUNITIES ONLY")
    print("=" * 70)
    for field, description in fields_to_check.items():
        count = biddable_field_counts[field]
        pct = (count / biddable_count * 100) if biddable_count > 0 else 0
        status = "✅" if pct >= 90 else "⚠️" if pct >= 70 else "❌"
        print(f"{status} {description:40} {count:>6,} / {biddable_count:,} ({pct:>5.1f}%)")
    print()
    
    # Open deadline opportunities coverage
    print("=" * 70)
    print("FIELD COVERAGE - OPEN DEADLINE OPPORTUNITIES ONLY")
    print("=" * 70)
    for field, description in fields_to_check.items():
        count = open_field_counts[field]
        pct = (count / open_deadline_count * 100) if open_deadline_count > 0 else 0
        status = "✅" if pct >= 90 else "⚠️" if pct >= 70 else "❌"
        print(f"{status} {description:40} {count:>6,} / {open_deadline_count:,} ({pct:>5.1f}%)")
    print()
    
    # Critical fields summary
    print("=" * 70)
    print("CRITICAL FIELDS SUMMARY (Open Deadline Opps)")
    print("=" * 70)
    
    critical_fields = {
        "NoticeId": "OPP_ID",
        "Sol#": "Notice ID", 
        "Title": "Title",
        "Description": "Description",
        "NaicsCode": "NAICS",
        "ResponseDeadLine": "Deadline",
        "SetASide": "Set-Aside",
    }
    
    all_critical = True
    for field, name in critical_fields.items():
        count = open_field_counts[field]
        pct = (count / open_deadline_count * 100) if open_deadline_count > 0 else 0
        status = "✅" if pct >= 80 else "⚠️" if pct >= 60 else "❌"
        print(f"{status} {name:20} {pct:>5.1f}% coverage")
        if pct < 80:
            all_critical = False
    
    print()
    if all_critical:
        print("✅ All critical fields have 80%+ coverage!")
    else:
        print("⚠️  Some critical fields have <80% coverage")
    print("=" * 70)


if __name__ == "__main__":
    analyze_coverage()