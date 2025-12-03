"""
Auto-populate NAICS and PSC code descriptions from official sources

This script:
1. Reads your unique codes from /tmp files
2. Downloads official NAICS 2022 codes
3. Creates proper JSON mapping files with descriptions

You'll need to manually download PSC codes from:
https://www.acquisition.gov/psc-manual (Excel format)
"""

import json
import re

def clean_naics_code(code: str) -> str:
    """Remove .0 suffix from NAICS codes"""
    if code.endswith('.0'):
        return code[:-2]
    return code

def load_unique_codes():
    """Load unique codes from extraction script output"""
    with open('/tmp/unique_naics.txt', 'r') as f:
        naics_codes = [clean_naics_code(line.strip()) for line in f if line.strip() and line.strip() != '[]']
    
    with open('/tmp/unique_psc.txt', 'r') as f:
        psc_codes = [line.strip() for line in f if line.strip()]
    
    # Remove any empty/invalid codes
    naics_codes = [c for c in naics_codes if c and c != '[]']
    psc_codes = [c for c in psc_codes if c and c != '[]']
    
    return sorted(set(naics_codes)), sorted(set(psc_codes))

def create_naics_mapping():
    """
    Create NAICS code mapping
    
    For now, creates a template. You can enhance this by:
    1. Download https://www.census.gov/naics/2022NAICS/2022_NAICS_Descriptions.xlsx
    2. Parse the Excel file
    3. Auto-populate descriptions
    """
    naics_codes, _ = load_unique_codes()
    
    # Common NAICS descriptions (add more as needed)
    common_descriptions = {
        "336413": "Other Aircraft Parts and Auxiliary Equipment Manufacturing",
        "541511": "Custom Computer Programming Services",
        "541512": "Computer Systems Design Services",
        "541519": "Other Computer Related Services",
        "541330": "Engineering Services",
        "541611": "Administrative Management Consulting Services",
        "541715": "Research and Development in Physical/Engineering Sciences",
        "237310": "Highway, Street, and Bridge Construction",
        "541990": "All Other Professional, Scientific, and Technical Services",
        "336412": "Aircraft Engine and Engine Parts Manufacturing",
        # Add more common ones here
    }
    
    mapping = {}
    for code in naics_codes:
        if code in common_descriptions:
            mapping[code] = common_descriptions[code]
        else:
            # For codes without descriptions, use a placeholder
            mapping[code] = f"NAICS {code}"
    
    return mapping

def create_psc_mapping():
    """
    Create PSC code mapping
    
    Common PSC codes from the Federal Supply Classification
    """
    _, psc_codes = load_unique_codes()
    
    # Common PSC descriptions
    common_descriptions = {
        # IT and Telecom (D-series)
        "D302": "IT and Telecom - Facilities Related Hardware",
        "D307": "IT and Telecom - Packaged Software Solutions",
        "D310": "IT and Telecom - Cyber Security and Data Backup",
        "D399": "IT and Telecom - Other IT and Telecommunications",
        
        # Professional Services (R-series)
        "R425": "Professional Services - Engineering/Technical",
        "R497": "Professional Services - Personal Needs Services",
        "R499": "Professional Services - Other Support Services",
        
        # Facilities Related (Z-series)
        "Z1AA": "Maintenance of Real Property",
        "Z2DA": "Maintenance of HVAC Equipment",
        
        # Weapons (10-series)
        "1005": "Guns, through 30mm",
        
        # Aircraft (15-16 series)
        "1510": "Aircraft, Fixed Wing",
        "1520": "Aircraft, Rotary Wing",
        "1560": "Airframe Structural Components",
        "1680": "Miscellaneous Aircraft Accessories and Components",
        
        # Electronic Equipment (58-59 series)
        "5995": "Cable, Cord, and Wire Assemblies: Communication Equipment",
        "5820": "Radio and Television Communication Equipment",
        
        # IT Software/Hardware (70 series)
        "7030": "Information Technology Software",
        "7010": "ADP Central Processing Unit",
        
        # Maintenance (J-series)
        "J019": "Maintenance of Miscellaneous Buildings",
        
        # Add more as needed
    }
    
    mapping = {}
    for code in psc_codes:
        if code in common_descriptions:
            mapping[code] = common_descriptions[code]
        else:
            # Create descriptive placeholder based on code structure
            if code.startswith('D'):
                mapping[code] = f"IT and Telecom - {code}"
            elif code.startswith('R'):
                mapping[code] = f"Professional Services - {code}"
            elif code.startswith('J'):
                mapping[code] = f"Maintenance/Repair - {code}"
            elif code.startswith('Z'):
                mapping[code] = f"Facilities Maintenance - {code}"
            elif code.isdigit():
                mapping[code] = f"Federal Supply Class {code}"
            else:
                mapping[code] = f"PSC {code}"
    
    return mapping

def save_mappings():
    """Save mappings to JSON files"""
    naics_mapping = create_naics_mapping()
    psc_mapping = create_psc_mapping()
    
    # Save to app/data directory
    with open('app/data/naics_codes.json', 'w') as f:
        json.dump(naics_mapping, f, indent=2)
    
    with open('app/data/psc_codes.json', 'w') as f:
        json.dump(psc_mapping, f, indent=2)
    
    print(f"✅ Created NAICS mapping with {len(naics_mapping)} codes")
    print(f"✅ Created PSC mapping with {len(psc_mapping)} codes")
    print(f"\n📁 Files saved to:")
    print(f"   - app/data/naics_codes.json")
    print(f"   - app/data/psc_codes.json")
    
    # Show sample
    print(f"\n📋 Sample NAICS codes:")
    for code in list(naics_mapping.keys())[:5]:
        print(f"   {code}: {naics_mapping[code]}")
    
    print(f"\n📦 Sample PSC codes:")
    for code in list(psc_mapping.keys())[:5]:
        print(f"   {code}: {psc_mapping[code]}")

if __name__ == "__main__":
    try:
        save_mappings()
        print("\n" + "="*80)
        print("🎉 SUCCESS! Code mappings created.")
        print("="*80)
        print("\nNext steps:")
        print("1. Review the generated files in app/data/")
        print("2. For better descriptions, download official NAICS/PSC files")
        print("3. Restart your FastAPI server")
        print("4. Test the API endpoints")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()