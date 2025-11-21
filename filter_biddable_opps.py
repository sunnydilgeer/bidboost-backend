import json
from datetime import datetime

# Load the full dataset
with open('sam_active_solicitations_full.json', 'r') as f:
    all_opps = json.load(f)

today = datetime.now().isoformat()

# Filter for TRULY biddable opportunities
biddable = []
for opp in all_opps:
    closing_date = opp.get('closing_date')
    archive_date = opp.get('metadata', {}).get('archive_date', '')
    
    # Must have a future closing date OR future archive date
    is_biddable = False
    
    if closing_date and closing_date > today:
        is_biddable = True
    elif not closing_date and archive_date and archive_date > today:
        # No deadline but archive date is in future - might still be open
        is_biddable = True
    
    if is_biddable:
        biddable.append(opp)

# Save filtered dataset
with open('sam_biddable_opportunities.json', 'w') as f:
    json.dump(biddable, f, indent=2, default=str)

print(f"📊 QUALITY FILTER RESULTS:")
print(f"   Total input: {len(all_opps):,}")
print(f"   Truly biddable: {len(biddable):,}")
print(f"   Filtered out: {len(all_opps) - len(biddable):,}")

# Statistics on biddable ones
with_deadlines = sum(1 for o in biddable if o.get('closing_date'))
with_values = sum(1 for o in biddable if o.get('value'))

print(f"\n✅ BIDDABLE OPPORTUNITIES:")
print(f"   With closing deadlines: {with_deadlines:,} ({with_deadlines/len(biddable)*100:.1f}%)")
print(f"   With contract values: {with_values:,}")

# Get deadline distribution
import collections
deadline_months = collections.Counter()
for opp in biddable:
    if opp.get('closing_date'):
        month = opp['closing_date'][:7]  # YYYY-MM
        deadline_months[month] += 1

print(f"\n📅 Deadlines by Month:")
for month in sorted(deadline_months.keys())[:6]:
    print(f"   {month}: {deadline_months[month]:,}")

print(f"\n💾 Saved to: sam_biddable_opportunities.json")
print(f"📦 File size: ~{len(json.dumps(biddable, default=str)) / 1024 / 1024:.1f} MB")
