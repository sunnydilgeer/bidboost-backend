"""
Parse official PSC Excel file and create complete JSON mapping
Updated for actual acquisition.gov file structure
"""

import pandas as pd
import json
import sys
from pathlib import Path

def parse_psc_excel(excel_path: str):
    """
    Parse PSC Excel file from acquisition.gov
    Expected columns: 
    - 'PSC CODE'
    - 'PRODUCT AND SERVICE CODE NAME' (short name)
    - 'PRODUCT AND SERVICE CODE FULL NAME (DESCRIPTION)' (full description)
    """
    print(f"📖 Reading {excel_path}...")
    
    try:
        df = pd.read_excel(excel_path)
        
        print(f"📋 Found columns: {list(df.columns)}")
        print(f"📊 Total rows: {len(df)}")
        
        # Verify expected columns exist
        if 'PSC CODE' not in df.columns:
            print("❌ Expected column 'PSC CODE' not found")
            return None
        
        # Determine which name column to use
        name_col = None
        if 'PRODUCT AND SERVICE CODE FULL NAME (DESCRIPTION)' in df.columns:
            name_col = 'PRODUCT AND SERVICE CODE FULL NAME (DESCRIPTION)'
            print("✅ Using full description column")
        elif 'PRODUCT AND SERVICE CODE NAME' in df.columns:
            name_col = 'PRODUCT AND SERVICE CODE NAME'
            print("✅ Using short name column")
        else:
            print("❌ Could not find description column")
            return None
        
        # Create mapping
        mapping = {}
        skipped = 0
        
        for _, row in df.iterrows():
            code = str(row['PSC CODE']).strip()
            
            # Get description (prefer full name, fall back to short name)
            desc = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
            
            # If full description is empty and short name exists, use that
            if not desc or desc == 'nan':
                if 'PRODUCT AND SERVICE CODE NAME' in df.columns:
                    desc = str(row['PRODUCT AND SERVICE CODE NAME']).strip()
            
            # Skip empty rows
            if code == 'nan' or not code or code == 'PSC CODE':
                skipped += 1
                continue
            
            if desc == 'nan' or not desc:
                # Use code itself as fallback
                desc = f"PSC {code}"
            
            # Clean up code
            code = code.replace('.0', '').strip()
            
            mapping[code] = desc
        
        print(f"\n✅ Parsed {len(mapping)} PSC codes (skipped {skipped} rows)")
        return mapping
        
    except Exception as e:
        print(f"❌ Error parsing Excel file: {e}")
        import traceback
        traceback.print_exc()
        return None

def save_psc_json(mapping: dict, output_path: str = "app/data/psc_codes.json"):
    """Save PSC mapping to JSON file"""
    
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

def check_coverage(mapping: dict, your_codes_file: str = "/tmp/unique_psc.txt"):
    """Check which codes from your data are covered"""
    
    if not Path(your_codes_file).exists():
        print(f"\n⚠️  Could not find {your_codes_file}")
        print("Run the extraction script first: python -m app.tasks.extract_unique_codes")
        return
    
    # Load your codes
    with open(your_codes_file, 'r') as f:
        your_codes = set([line.strip() for line in f if line.strip() and line.strip() != '[]'])
    
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
        
        # Categorize missing codes
        by_category = {}
        for code in missing:
            if code.isdigit():
                cat = "Numeric codes"
            elif code[0].isalpha():
                cat = f"{code[0]}-series codes"
            else:
                cat = "Other codes"
            
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(code)
        
        for cat in sorted(by_category.keys()):
            codes = by_category[cat]
            print(f"\n   {cat}: {len(codes)} codes")
            for code in sorted(codes)[:5]:
                print(f"      {code}")
            if len(codes) > 5:
                print(f"      ... and {len(codes) - 5} more")
        
        # Save missing
        with open('/tmp/missing_psc.txt', 'w') as f:
            for code in sorted(missing):
                f.write(f"{code}\n")
        print(f"\n💾 Saved all missing codes to /tmp/missing_psc.txt")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_psc.py /path/to/PSC_April_2025.xlsx")
        sys.exit(1)
    
    excel_path = sys.argv[1]
    
    if not Path(excel_path).exists():
        print(f"❌ File not found: {excel_path}")
        sys.exit(1)
    
    # Parse Excel
    mapping = parse_psc_excel(excel_path)
    
    if mapping:
        # Save to JSON
        saved_mapping = save_psc_json(mapping)
        
        # Check coverage
        check_coverage(saved_mapping)
        
        print("\n🎉 PSC codes updated successfully!")
        print("Restart your FastAPI server to use the new mappings.")
    else:
        print("\n❌ Failed to parse PSC file")
        sys.exit(1)