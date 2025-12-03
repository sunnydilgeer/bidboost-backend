"""
Filter SAM.GOV CSV to extract ONLY open/biddable opportunities
Excludes: closed, expired, and awarded contracts
"""
import pandas as pd
import json
from datetime import datetime, timezone
from pathlib import Path

def filter_open_opportunities(csv_path: str, output_json: str = "sam_open_opportunities.json"):
    """
    Filter ContractOpportunitiesFullCSV for open opportunities
    
    Criteria:
    - response_deadline must be in the future
    - type should be biddable (Solicitation, Sources Sought, etc.)
    - exclude awarded/closed contracts
    """
    
    print(f"📂 Reading CSV: {csv_path}")
    
    # Read CSV with explicit encoding (SAM.gov uses cp1252/windows-1252)
    df = pd.read_csv(csv_path, encoding='cp1252', low_memory=False)
    
    initial_count = len(df)
    print(f"✅ Loaded {initial_count:,} total opportunities\n")
    
    # Show available columns
    print("📋 Available columns:")
    for i, col in enumerate(df.columns, 1):
        print(f"  {i}. {col}")
    print()
    
    # Current time in UTC
    now = datetime.now(timezone.utc)
    print(f"🕐 Current time (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Step 1: Filter by notice type (exclude awards, intent to cancel, etc.)
    biddable_types = [
        'Solicitation',
        'Sources Sought',
        'Presolicitation',
        'Combined Synopsis/Solicitation',
        'Special Notice'
    ]
    
    print(f"🔍 STEP 1: Filtering by biddable notice types...")
    if 'Type' in df.columns:
        print(f"  Notice types in data:")
        type_counts = df['Type'].value_counts()
        for notice_type, count in type_counts.items():
            marker = "✅" if notice_type in biddable_types else "❌"
            print(f"    {marker} {notice_type}: {count:,}")
        
        df_biddable = df[df['Type'].isin(biddable_types)].copy()
        print(f"\n  ✅ Kept {len(df_biddable):,} biddable opportunities")
        print(f"  ❌ Excluded {initial_count - len(df_biddable):,} non-biddable notices\n")
    else:
        print("  ⚠️  'Type' column not found, skipping type filter\n")
        df_biddable = df.copy()
    
    # Step 2: Filter by response deadline (must be in future)
    print(f"🔍 STEP 2: Filtering by response deadline...")
    
    if 'ResponseDeadLine' not in df_biddable.columns:
        print("  ❌ ERROR: 'ResponseDeadLine' column not found!")
        return
    
    # Parse deadlines
    def parse_deadline(deadline_str):
        """Parse various deadline formats"""
        if pd.isna(deadline_str):
            return None
        
        deadline_str = str(deadline_str).strip()
        if not deadline_str or deadline_str.lower() == 'nan':
            return None
        
        # Try various formats
        formats = [
            '%Y-%m-%dT%H:%M:%S%z',       # 2025-12-10T14:00:00+09:00
            '%Y-%m-%d %H:%M:%S%z',       # 2025-11-26 20:54:10-05
            '%Y-%m-%dT%H:%M:%S',         # 2025-12-10T14:00:00
            '%Y-%m-%d %H:%M:%S',         # 2025-11-26 20:54:10
            '%Y-%m-%d',                  # 2025-12-10
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(deadline_str[:26], fmt)
                # If no timezone, assume UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, IndexError):
                continue
        
        return None
    
    # Apply deadline parsing
    df_biddable['deadline_parsed'] = df_biddable['ResponseDeadLine'].apply(parse_deadline)
    
    # Count parsed deadlines
    valid_deadlines = df_biddable['deadline_parsed'].notna().sum()
    invalid_deadlines = len(df_biddable) - valid_deadlines
    
    print(f"  ✅ Successfully parsed: {valid_deadlines:,} deadlines")
    print(f"  ⚠️  Failed to parse: {invalid_deadlines:,} deadlines")
    
    # Filter for future deadlines only
    df_open = df_biddable[df_biddable['deadline_parsed'] > now].copy()
    
    expired_count = valid_deadlines - len(df_open)
    print(f"\n  ✅ OPEN opportunities: {len(df_open):,}")
    print(f"  ❌ EXPIRED opportunities: {expired_count:,}")
    print(f"  ⚠️  No deadline: {invalid_deadlines:,}\n")
    
    # Step 3: Show deadline distribution
    if len(df_open) > 0:
        print("📊 OPEN Opportunities Deadline Distribution:")
        # Calculate days until deadline for each row
        df_open['days_until_deadline'] = df_open['deadline_parsed'].apply(
            lambda x: (x - now).days if pd.notna(x) else None
        )
        
        urgent = len(df_open[df_open['days_until_deadline'] <= 7])
        soon = len(df_open[(df_open['days_until_deadline'] > 7) & (df_open['days_until_deadline'] <= 30)])
        later = len(df_open[df_open['days_until_deadline'] > 30])
        
        print(f"  🔴 Urgent (≤7 days): {urgent:,}")
        print(f"  🟡 Soon (8-30 days): {soon:,}")
        print(f"  🟢 Later (>30 days): {later:,}\n")
    
    # Step 4: Export to JSON
    print(f"💾 Exporting to JSON...")
    
    # Drop the parsed deadline column (not JSON serializable)
    df_open = df_open.drop(columns=['deadline_parsed', 'days_until_deadline'], errors='ignore')
    
    # Convert to records (list of dicts)
    opportunities = df_open.to_dict('records')
    
    # Save JSON
    output_path = Path(output_json)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(opportunities, f, indent=2, default=str)
    
    print(f"✅ Saved {len(opportunities):,} open opportunities to: {output_path}")
    
    # Show file size
    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"📦 File size: {file_size_mb:.2f} MB\n")
    
    # Summary
    print("=" * 80)
    print("📊 FILTERING SUMMARY")
    print("=" * 80)
    print(f"  Initial records: {initial_count:,}")
    print(f"  Biddable types: {len(df_biddable):,}")
    print(f"  ✅ OPEN (not expired): {len(df_open):,}")
    print(f"  ❌ Filtered out: {initial_count - len(df_open):,}")
    print(f"  📈 Open rate: {(len(df_open) / initial_count * 100):.1f}%")
    print("=" * 80)
    
    return df_open


if __name__ == "__main__":
    import sys
    
    # Usage: python filter_open_opportunities.py [csv_path] [output_json]
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "ContractOpportunitiesFullCSV.csv"
    output_json = sys.argv[2] if len(sys.argv) > 2 else "sam_open_opportunities.json"
    
    try:
        filter_open_opportunities(csv_path, output_json)
    except FileNotFoundError:
        print(f"❌ ERROR: File not found: {csv_path}")
        print("\nUsage: python filter_open_opportunities.py [csv_path] [output_json]")
        print("Example: python filter_open_opportunities.py ContractOpportunitiesFullCSV.csv sam_open_opportunities.json")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)