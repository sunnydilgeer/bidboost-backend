"""
Map SAM.gov CSV columns to sync script format
Transforms sam_open_opportunities.json → sam_biddable_opportunities.json
"""
import json
from pathlib import Path

def map_columns(input_file: str = "sam_open_opportunities.json", 
                output_file: str = "sam_biddable_opportunities.json"):
    """
    Map SAM.gov CSV column names to sync script format
    
    CSV Format → Sync Format:
    - NoticeId → notice_id
    - Title → title
    - Description → description
    - Department/Ind.Agency → agency
    - NaicsCode → naics_code
    - ResponseDeadLine → response_deadline
    - etc.
    """
    
    print(f"📂 Reading: {input_file}")
    
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ ERROR: File not found: {input_file}")
        return
    
    # Load data
    with open(input_path, 'r', encoding='utf-8') as f:
        opportunities = json.load(f)
    
    total = len(opportunities)
    print(f"✅ Loaded {total:,} opportunities\n")
    
    # Column mapping (CSV → Sync format)
    column_map = {
        'NoticeId': 'notice_id',
        'Title': 'title',
        'Sol#': 'solicitation_number',
        'Department/Ind.Agency': 'agency',
        'Office': 'office',
        'PostedDate': 'posted_date',
        'Type': 'type',
        'ResponseDeadLine': 'response_deadline',
        'NaicsCode': 'naics_code',
        'ClassificationCode': 'classification_code',
        'SetASideCode': 'set_aside_code',
        'SetASide': 'set_aside_type',
        'State': 'state',
        'City': 'city',
        'ZipCode': 'zip_code',
        'PopState': 'pop_state',
        'PopCity': 'pop_city',
        'Link': 'source_url',
        'Description': 'description',
        'PrimaryContactEmail': 'contact_email',
        'PrimaryContactFullname': 'contact_name',
        'PrimaryContactPhone': 'contact_phone',
    }
    
    print("🔄 Mapping columns...")
    print("   SAM.gov CSV → Sync Format")
    for old_name, new_name in column_map.items():
        print(f"   {old_name:30} → {new_name}")
    print()
    
    # Transform each opportunity
    mapped_opportunities = []
    skipped = 0
    
    for opp in opportunities:
        try:
            mapped = {}
            
            # Map all columns
            for csv_col, sync_col in column_map.items():
                value = opp.get(csv_col)
                
                # Handle NaN, None, empty strings
                if value is None or str(value).lower() in ['nan', 'nat', '']:
                    mapped[sync_col] = None
                else:
                    mapped[sync_col] = value
            
            mapped_opportunities.append(mapped)
            
        except Exception as e:
            print(f"⚠️  Skipped 1 opportunity due to error: {e}")
            skipped += 1
            continue
    
    print(f"✅ Mapped {len(mapped_opportunities):,} opportunities")
    if skipped > 0:
        print(f"⚠️  Skipped {skipped} opportunities due to errors")
    print()
    
    # Sample output
    print("📋 SAMPLE MAPPED OPPORTUNITY:")
    if mapped_opportunities:
        sample = mapped_opportunities[0]
        print(json.dumps(sample, indent=2, default=str)[:500] + "...")
    print()
    
    # Save to JSON
    output_path = Path(output_file)
    print(f"💾 Saving to: {output_path}")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mapped_opportunities, f, indent=2, default=str)
    
    # File size
    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"✅ Saved {len(mapped_opportunities):,} opportunities")
    print(f"📦 File size: {file_size_mb:.2f} MB\n")
    
    # Summary
    print("=" * 80)
    print("📊 MAPPING SUMMARY")
    print("=" * 80)
    print(f"  Input file: {input_file}")
    print(f"  Output file: {output_file}")
    print(f"  Total opportunities: {len(mapped_opportunities):,}")
    print(f"  Columns mapped: {len(column_map)}")
    print(f"  Ready for sync: ✅")
    print("=" * 80)
    
    print("\n🚀 NEXT STEPS:")
    print("  1. Clear Pinecone: python clear_pinecone.py")
    print("  2. Sync to Pinecone: python -m app.tasks.sam_sync --source biddable")
    print("  3. Verify: python inspect_pinecone.py")


if __name__ == "__main__":
    import sys
    
    # Usage: python map_sam_columns.py [input_file] [output_file]
    input_file = sys.argv[1] if len(sys.argv) > 1 else "sam_open_opportunities.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "sam_biddable_opportunities.json"
    
    try:
        map_columns(input_file, output_file)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)