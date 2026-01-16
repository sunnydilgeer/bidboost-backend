"""
Analyze ContractOpportunitiesFullCSV.csv by sectors and create summary JSON
Similar to the sector analysis from December 2024
"""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

CSV_FILE = Path("./data/ContractOpportunitiesFullCSV.csv")
OUTPUT_FILE = Path("./co_sector_analysis.json")

# NAICS to Sector mapping (add more as needed)
NAICS_TO_SECTOR = {
    # Defense & Aerospace
    "336411": "Defense & Aerospace",
    "336412": "Defense & Aerospace", 
    "336413": "Defense & Aerospace",
    "336414": "Defense & Aerospace",
    "336415": "Defense & Aerospace",
    "336419": "Defense & Aerospace",
    "332994": "Defense & Aerospace",
    
    # Electronics
    "334290": "Electronics Manufacturing",
    "334310": "Electronics Manufacturing",
    "334220": "Electronics Manufacturing",
    "334417": "Electronics Manufacturing",
    "334418": "Electronics Manufacturing",
    "334511": "Electronics Manufacturing",
    "334513": "Electronics Manufacturing",
    
    # Engines & Power
    "333618": "Engines & Power Equipment",
    "333612": "Engines & Power Equipment",
    "333611": "Engines & Power Equipment",
    "335312": "Engines & Power Equipment",
    
    # Industrial Components
    "332919": "Industrial Components",
    "332722": "Industrial Components",
    "332999": "Industrial Components",
    "333613": "Industrial Components",
    "332996": "Industrial Components",
    
    # Fasteners & Hardware
    "332722": "Fasteners & Hardware",
    "332510": "Fasteners & Hardware",
    
    # Instruments & Sensors
    "334511": "Instruments & Sensors",
    "334513": "Instruments & Sensors",
    "334515": "Instruments & Sensors",
    "334516": "Instruments & Sensors",
    "334519": "Instruments & Sensors",
    
    # Communications & Radar
    "334220": "Communications & Radar",
    "334290": "Communications & Radar",
    
    # Construction
    "236220": "Construction",
    "237990": "Construction",
    "238": "Construction",  # Prefix match
    
    # IT Services
    "541511": "IT Services",
    "541512": "IT Services",
    "541513": "IT Services",
    "541519": "IT Services",
    
    # Professional Services
    "541611": "Professional Services",
    "541612": "Professional Services",
    "541614": "Professional Services",
    "541618": "Professional Services",
    "541990": "Professional Services",
    
    # Healthcare
    "621": "Healthcare & Medical",  # Prefix
    "339112": "Healthcare & Medical",
    "339113": "Healthcare & Medical",
    "339114": "Healthcare & Medical",
    "339115": "Healthcare & Medical",
    
    # Telecommunications
    "517": "Telecommunications",  # Prefix
    
    # Shipbuilding
    "336611": "Shipbuilding & Marine",
    "336612": "Shipbuilding & Marine",
    
    # Logistics
    "484": "Logistics & Transportation",  # Prefix
    "488": "Logistics & Transportation",  # Prefix
}

def get_sector_from_naics(naics_code: str) -> str:
    """Map NAICS code to sector."""
    if not naics_code:
        return "Unknown"
    
    # Exact match
    if naics_code in NAICS_TO_SECTOR:
        return NAICS_TO_SECTOR[naics_code]
    
    # Prefix match (for broader categories)
    for prefix, sector in NAICS_TO_SECTOR.items():
        if naics_code.startswith(prefix):
            return NAICS_TO_SECTOR[prefix]
    
    # Manufacturing catch-all
    if naics_code.startswith("3"):
        return "Other Manufacturing"
    
    return "Other"


def get_icp_group(sector: str) -> str:
    """Map sector to ICP group."""
    defense_sectors = ["Defense & Aerospace", "Engines & Power Equipment", 
                      "Industrial Components", "Electronics Manufacturing",
                      "Fasteners & Hardware", "Instruments & Sensors",
                      "Communications & Radar", "Metal Fabrication",
                      "Precision Manufacturing", "Shipbuilding & Marine"]
    
    if sector in defense_sectors:
        return "defense_manufacturing"
    elif sector == "Construction":
        return "construction"
    elif sector == "Facilities & Maintenance":
        return "facilities"
    elif sector == "Healthcare & Medical":
        return "healthcare"
    elif sector == "IT Services":
        return "it_services"
    elif sector == "Telecommunications":
        return "telecom"
    elif sector == "Logistics & Transportation":
        return "logistics"
    elif sector == "Professional Services":
        return "professional"
    elif sector == "Other Manufacturing":
        return "other_manufacturing"
    else:
        return "other"


def parse_deadline(date_str: str):
    """Parse deadline."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def get_urgency(deadline_str: str) -> str:
    """Calculate urgency category based on deadline."""
    deadline = parse_deadline(deadline_str)
    
    if not deadline:
        return "No deadline"
    
    now = datetime.now()
    days_until = (deadline - now).days
    
    if days_until < 0:
        return "Expired"
    elif days_until <= 7:
        return "Urgent (≤7d)"
    elif days_until <= 14:
        return "Soon (8-14d)"
    elif days_until <= 30:
        return "Normal (15-30d)"
    elif days_until <= 90:
        return "Extended (31-90d)"
    else:
        return "Long-term (90d+)"


def analyze():
    print("=" * 70)
    print("CONTRACT OPPORTUNITIES SECTOR ANALYSIS")
    print("=" * 70)
    print()
    
    total_records = 0
    biddable_count = 0
    defense_manufacturing_count = 0
    
    by_opportunity_type = Counter()
    by_sector = Counter()
    by_icp_group = Counter()
    by_set_aside = Counter()
    by_urgency = Counter()
    top_naics_codes = Counter()
    
    print("📖 Reading CSV...")
    
    with open(CSV_FILE, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            total_records += 1
            
            # Extract fields
            opp_type = row.get("Type", "").strip()
            base_type = row.get("BaseType", "").strip()
            active = row.get("Active", "").strip().lower()
            naics_code = row.get("NaicsCode", "").strip()
            set_aside = row.get("SetASide", "").strip()
            deadline_str = row.get("ResponseDeadLine", "").strip()
            
            # Opportunity type
            by_opportunity_type[opp_type] += 1
            
            # Biddable check
            is_biddable = (base_type in ["Solicitation", "Combined Synopsis/Solicitation"] and 
                          active == "yes")
            
            if is_biddable:
                biddable_count += 1
                
                # Sector analysis
                sector = get_sector_from_naics(naics_code)
                by_sector[sector] += 1
                
                # ICP group
                icp_group = get_icp_group(sector)
                by_icp_group[icp_group] += 1
                
                if icp_group == "defense_manufacturing":
                    defense_manufacturing_count += 1
                
                # Set-aside
                if set_aside:
                    by_set_aside[set_aside] += 1
                else:
                    by_set_aside["Open Competition"] += 1
                
                # Urgency
                urgency = get_urgency(deadline_str)
                by_urgency[urgency] += 1
                
                # Top NAICS
                if naics_code:
                    top_naics_codes[naics_code] += 1
            
            if total_records % 10000 == 0:
                print(f"  Processed {total_records:,} rows...")
    
    print()
    print(f"✅ Processed {total_records:,} total records")
    print(f"✅ Found {biddable_count:,} biddable opportunities")
    print()
    
    # Create analysis JSON
    analysis = {
        "analysis_date": datetime.now().isoformat(),
        "total_records": total_records,
        "biddable_count": biddable_count,
        "defense_manufacturing_count": defense_manufacturing_count,
        "by_opportunity_type": dict(by_opportunity_type.most_common()),
        "by_sector": dict(by_sector.most_common()),
        "by_icp_group": dict(by_icp_group.most_common()),
        "by_set_aside": dict(by_set_aside.most_common()),
        "by_urgency": dict(by_urgency.most_common()),
        "top_naics_codes": dict(top_naics_codes.most_common(20)),
    }
    
    # Save to JSON
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(analysis, f, indent=2)
    
    print(f"📊 Analysis saved to: {OUTPUT_FILE}")
    print()
    
    # Print summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total Records: {total_records:,}")
    print(f"Biddable Opportunities: {biddable_count:,}")
    print(f"Defense Manufacturing: {defense_manufacturing_count:,}")
    print()
    
    print("Top 5 Sectors:")
    for sector, count in by_sector.most_common(5):
        pct = (count / biddable_count * 100) if biddable_count > 0 else 0
        print(f"  {sector:40} {count:>6,} ({pct:>5.1f}%)")
    print()
    
    print("Top 5 Set-Asides:")
    for set_aside, count in by_set_aside.most_common(5):
        pct = (count / biddable_count * 100) if biddable_count > 0 else 0
        print(f"  {set_aside[:50]:50} {count:>6,} ({pct:>5.1f}%)")
    print()
    
    print("By Urgency:")
    for urgency, count in by_urgency.most_common():
        pct = (count / biddable_count * 100) if biddable_count > 0 else 0
        print(f"  {urgency:30} {count:>6,} ({pct:>5.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    analyze()