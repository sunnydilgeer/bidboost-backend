#!/usr/bin/env python3
"""
FTS Data Quality Analyzer
Identifies records with missing critical fields and groups them for investigation
"""
import json
from collections import defaultdict
from pathlib import Path

# Critical fields that should rarely be null
CRITICAL_FIELDS = [
    "cpv_codes",
    "contract_value",
    "authority_name",
    "description",
]

# Award-specific fields
AWARD_FIELDS = [
    "supplier_name",
    "award_date",
]

# Opportunity-specific fields
OPPORTUNITY_FIELDS = [
    "deadline",
]

def analyze_null_patterns(json_file="fts_live_rich.json"):
    """Analyze which fields are null and group by patterns"""
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    print(f"\n{'='*70}")
    print(f"FTS DATA QUALITY REPORT")
    print(f"{'='*70}")
    print(f"Total records: {len(data)}\n")
    
    # Track null counts per field
    null_counts = defaultdict(int)
    empty_counts = defaultdict(int)
    
    # Group problematic records
    missing_cpv = []
    missing_value = []
    missing_authority = []
    missing_description = []
    missing_supplier = []
    missing_multiple = []
    
    for record in data:
        is_award = record.get("notice_type") == "award"
        issues = []
        
        # Check critical fields
        if not record.get("cpv_codes") or len(record.get("cpv_codes", [])) == 0:
            null_counts["cpv_codes"] += 1
            issues.append("cpv_codes")
            missing_cpv.append(record)
        
        if not record.get("contract_value"):
            null_counts["contract_value"] += 1
            issues.append("contract_value")
            missing_value.append(record)
        
        if not record.get("authority_name"):
            null_counts["authority_name"] += 1
            issues.append("authority_name")
            missing_authority.append(record)
        
        if not record.get("description"):
            null_counts["description"] += 1
            issues.append("description")
            missing_description.append(record)
        
        # Award-specific
        if is_award and not record.get("supplier_name"):
            null_counts["supplier_name"] += 1
            issues.append("supplier_name")
            missing_supplier.append(record)
        
        # Track records with multiple issues
        if len(issues) >= 2:
            missing_multiple.append({
                "tender_id": record.get("tender_id"),
                "url": record.get("url"),
                "notice_type": record.get("notice_type"),
                "issues": issues
            })
    
    # Print summary
    print("FIELD NULL RATES:")
    print("-" * 70)
    for field in CRITICAL_FIELDS + AWARD_FIELDS:
        count = null_counts.get(field, 0)
        percentage = (count / len(data)) * 100
        print(f"  {field:20s}: {count:4d} / {len(data):4d} ({percentage:5.1f}% missing)")
    
    print(f"\n{'='*70}")
    print("PROBLEMATIC RECORDS (sorted by severity)")
    print('='*70)
    
    # Most problematic: multiple missing fields
    if missing_multiple:
        print(f"\n🔴 MULTIPLE ISSUES ({len(missing_multiple)} records):")
        print("-" * 70)
        for rec in missing_multiple[:10]:  # Show top 10
            print(f"  {rec['tender_id']} ({rec['notice_type']})")
            print(f"    Missing: {', '.join(rec['issues'])}")
            print(f"    URL: {rec['url']}\n")
        
        if len(missing_multiple) > 10:
            print(f"  ... and {len(missing_multiple) - 10} more\n")
    
    # Group by individual issues
    issue_groups = [
        ("CPV codes", missing_cpv),
        ("Contract value", missing_value),
        ("Authority name", missing_authority),
        ("Description", missing_description),
        ("Supplier name (awards)", missing_supplier),
    ]
    
    for issue_name, records in issue_groups:
        if records:
            print(f"\n🟡 MISSING {issue_name.upper()} ({len(records)} records):")
            print("-" * 70)
            
            # Show sample URLs (first 5)
            for rec in records[:5]:
                print(f"  {rec.get('tender_id')} - {rec.get('title', 'No title')[:40]}")
                print(f"    {rec.get('url')}\n")
            
            if len(records) > 5:
                print(f"  ... and {len(records) - 5} more\n")
    
    # Export problematic URLs for testing
    print(f"\n{'='*70}")
    print("EXPORTING SAMPLE URLS FOR TESTING")
    print('='*70)
    
    test_urls = {
        "missing_cpv": [r["url"] for r in missing_cpv[:3]],
        "missing_value": [r["url"] for r in missing_value[:3]],
        "missing_authority": [r["url"] for r in missing_authority[:3]],
        "missing_multiple": [r["url"] for r in missing_multiple[:3]],
    }
    
    with open("problematic_urls.json", "w") as f:
        json.dump(test_urls, f, indent=2)
    
    print("✅ Saved sample URLs to: problematic_urls.json")
    print("\nYou can now:")
    print("  1. Visit these URLs in a browser to inspect HTML structure")
    print("  2. Use web_fetch to get page content")
    print("  3. Update scraper selectors based on patterns found\n")
    
    # Calculate overall quality score
    records_with_all_critical = sum(
        1 for r in data 
        if r.get("cpv_codes") and r.get("contract_value") and 
           r.get("authority_name") and r.get("description")
    )
    quality_score = (records_with_all_critical / len(data)) * 100
    
    print(f"{'='*70}")
    print(f"OVERALL DATA QUALITY SCORE: {quality_score:.1f}%")
    print(f"({records_with_all_critical}/{len(data)} records have all critical fields)")
    print(f"{'='*70}\n")


def show_extraction_tips():
    """Show tips for fixing common null issues"""
    print("\n" + "="*70)
    print("COMMON FIXES FOR NULL VALUES")
    print("="*70)
    
    tips = [
        ("Missing CPV codes", [
            "• Check if CPV is in a <table> instead of definition list",
            "• Look for 'Main CPV code' or 'Additional CPV code' headings",
            "• Try broader regex: r'\\d{8}' to catch any 8-digit codes"
        ]),
        ("Missing contract value", [
            "• Check for 'Total value', 'Estimated value', 'Contract value'",
            "• Look in both header and contract details sections",
            "• Try multiple currency symbols: £, €, GBP"
        ]),
        ("Missing authority name", [
            "• Authority might be in <address> tag",
            "• Look for 'Contracting authority', 'Buyer', 'Organisation'",
            "• First line after heading is usually the name"
        ]),
        ("Missing supplier name", [
            "• Check 'Contractor', 'Supplier', 'Awarded to' headings",
            "• May be in a separate <dl> or <div> section",
            "• Filter out placeholder text like 'To be confirmed'"
        ]),
    ]
    
    for issue, solutions in tips:
        print(f"\n{issue}:")
        for solution in solutions:
            print(f"  {solution}")
    
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    analyze_null_patterns()
    show_extraction_tips()