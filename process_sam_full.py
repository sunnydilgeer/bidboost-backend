from app.services.sam_csv_processor import SAMCSVProcessor
import json

csv_path = "data/sam_gov/ContractOpportunitiesFullCSV.csv"
processor = SAMCSVProcessor(csv_path)

print("=" * 60)
print("PROCESSING FULL SAM.GOV DATASET")
print("Extracting ALL active solicitations...")
print("=" * 60)

# Get ALL active solicitations (no max_records limit)
solicitations = processor.process_csv(
    max_records=None,  # Process everything!
    filter_types=["Solicitation", "Combined Synopsis/Solicitation"],
    filter_active_only=True
)

# Get statistics
stats = processor.get_statistics(solicitations)

print("\n" + "=" * 60)
print("📊 FINAL STATISTICS")
print("=" * 60)
print(f"Total active solicitations: {stats['total']:,}")
print(f"With deadlines: {stats['with_deadlines']:,} ({stats['with_deadlines']/stats['total']*100:.1f}%)")
print(f"With values: {stats['with_values']:,} ({stats['with_values']/stats['total']*100:.1f}%)")
print(f"SME suitable: {stats['sme_suitable']:,} ({stats['sme_suitable']/stats['total']*100:.1f}%)")

print(f"\n🏆 Top 10 States by Opportunity Count:")
top_states = sorted(stats['by_state'].items(), key=lambda x: -x[1])[:10]
for state, count in top_states:
    print(f"   {state}: {count:,}")

print(f"\n🎯 Set-Aside Distribution:")
top_set_asides = sorted(stats['by_set_aside'].items(), key=lambda x: -x[1])[:10]
for set_aside, count in top_set_asides:
    display = set_aside if set_aside else "Unrestricted (Full & Open)"
    print(f"   {display}: {count:,}")

# Save to JSON
output_file = 'sam_active_solicitations_full.json'
with open(output_file, 'w') as f:
    json.dump([s.model_dump() for s in solicitations], f, indent=2, default=str)

print(f"\n💾 Saved {len(solicitations):,} solicitations to {output_file}")
print(f"📦 File size: ~{len(json.dumps([s.model_dump() for s in solicitations], default=str)) / 1024 / 1024:.1f} MB")
