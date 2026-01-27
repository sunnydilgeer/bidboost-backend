from app.database import SessionLocal
from app.models.company import OpportunityChain
from sqlalchemy import func

db = SessionLocal()

# Check what we have
total = db.query(OpportunityChain).count()
print(f"Total chains: {total}")

# Quality breakdown
stats = db.query(
    OpportunityChain.base_description_quality,
    func.count(OpportunityChain.id)
).group_by(OpportunityChain.base_description_quality).all()

print("\nDescription Quality:")
for quality, count in stats:
    print(f"  {quality}: {count}")

# Check needs SOW extraction
needs_sow = db.query(OpportunityChain).filter_by(needs_sow_extraction=True).count()
print(f"\nNeeds SOW extraction: {needs_sow}")

# Sample a good one
good = db.query(OpportunityChain).filter_by(base_description_quality="GOOD").first()
if good:
    print(f"\nSample GOOD description:")
    print(f"  Sol#: {good.solicitation_number}")
    print(f"  Base notice: {good.base_notice_id}")
    print(f"  Amendment count: {good.notice_count - 1}")
    print(f"  Description preview: {good.base_description[:200]}...")

# Sample a poor one
poor = db.query(OpportunityChain).filter_by(base_description_quality="POOR").first()
if poor:
    print(f"\nSample POOR description:")
    print(f"  Sol#: {poor.solicitation_number}")
    print(f"  Base notice: {poor.base_notice_id}")
    print(f"  Description: {poor.base_description}")

db.close()