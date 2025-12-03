"""
Parse official NAICS 2022 Excel file and create complete JSON mapping
Updated for actual Census Bureau file structure
"""

import pandas as pd
import json
import sys
from pathlib import Path

def parse_naics_excel(excel_path: str):
    """
    Parse NAICS 2022 Excel file
    Expected columns: 'Code', 'Title', 'Description'
    """
    print(f"📖 Reading {excel_path}...")
    
    try:
        df = pd.read_excel(excel_path)
        
        print(f"📋 Found columns: {list(df.columns)}")
        print(f"📊 Total rows: {len(df)}")
        
        # Verify expected columns exist
        if 'Code' not in df.columns or 'Title' not in df.columns:
            print("❌ Expected columns 'Code' and 'Title' not found")
            return None
        
        # Create mapping
        mapping = {}
        skipped = 0
        
        for _, row in df.iterrows():
            code = str(row['Code']).strip()
            title = str(row['Title']).strip()
            
            # Skip empty rows or headers
            if code == 'nan' or title == 'nan' or not code or code == 'Code':
                skipped += 1
                continue
            
            # Remove any decimal points
            code = code.replace('.0', '')
            
            # Only include numeric codes (skip section headers)
            if code.isdigit():
                mapping[code] = title
        
        print(f"\n✅ Parsed {len(mapping)} NAICS codes (skipped {skipped} non-code rows)")
        return mapping
        
    except Exception as e:
        print(f"❌ Error parsing Excel file: {e}")
        import traceback
        traceback.print_exc()
        return None

def save_naics_json(mapping: dict, output_path: str = "app/data/naics_codes.json"):
    """Save NAICS mapping to JSON file"""
    
    # Sort by code for easier reading
    sorted_mapping = dict(sorted(mapping.items()))
    
    with open(output_path, 'w') as f:
        json.dump(sorted_mapping, f, indent=2)
    
    print(f"\n💾 Saved {len(sorted_mapping)} codes to {output_path}")
    
    # Show sample
    print("\n📋 Sample entries:")
    for code in list(sorted_mapping.keys())[:10]:
        desc = sorted_mapping[code][:60] + "..." if len(sorted_mapping[code]) > 60 else sorted_mapping[code]
        print(f"   {code}: {desc}")
    
    return sorted_mapping

def check_coverage(mapping: dict, your_codes_file: str = "/tmp/unique_naics.txt"):
    """Check which codes from your data are covered"""
    
    if not Path(your_codes_file).exists():
        print(f"\n⚠️  Could not find {your_codes_file}")
        print("Run the extraction script first: python -m app.tasks.extract_unique_codes")
        return
    
    # Load your codes
    with open(your_codes_file, 'r') as f:
        your_codes = set()
        for line in f:
            code = line.strip().replace('.0', '')
            if code and code != '[]':
                your_codes.add(code)
    
    # Find missing
    missing = your_codes - set(mapping.keys())
    covered = your_codes & set(mapping.keys())
    
    coverage_pct = (len(covered) / len(your_codes) * 100) if your_codes else 0
    
    print(f"\n📊 Coverage Report:")
    print(f"   Total codes in your data:     {len(your_codes)}")
    print(f"   Covered by official list:     {len(covered)} ({coverage_pct:.1f}%)")
    print(f"   Missing from official list:   {len(missing)}")
    
    if missing:
        print(f"\n❌ Missing codes:")
        for code in sorted(missing)[:20]:
            print(f"   {code}")
        if len(missing) > 20:
            print(f"   ... and {len(missing) - 20} more")
        
        # Save missing
        with open('/tmp/missing_naics.txt', 'w') as f:
            for code in sorted(missing):
                f.write(f"{code}\n")
        print(f"\n💾 Saved missing codes to /tmp/missing_naics.txt")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_naics.py /path/to/2022_NAICS_Descriptions.xlsx")
        sys.exit(1)
    
    excel_path = sys.argv[1]
    
    if not Path(excel_path).exists():
        print(f"❌ File not found: {excel_path}")
        sys.exit(1)
    
    # Parse Excel
    mapping = parse_naics_excel(excel_path)
    
    if mapping:
        # Save to JSON
        saved_mapping = save_naics_json(mapping)
        
        # Check coverage
        check_coverage(saved_mapping)
        
        print("\n🎉 NAICS codes updated successfully!")
        print("Restart your FastAPI server to use the new mappings.")
    else:
        print("\n❌ Failed to parse NAICS file")
        sys.exit(1)