from app.database import SessionLocal
from app.models.company import OpportunityChain
from sqlalchemy import func

db = SessionLocal()

# Check for duplicate base_notice_ids
duplicates = db.query(
    OpportunityChain.base_notice_id,
    func.count(OpportunityChain.base_notice_id).label('count')
).filter(
    OpportunityChain.pinecone_id.isnot(None)
).group_by(
    OpportunityChain.base_notice_id
).having(
    func.count(OpportunityChain.base_notice_id) > 1
).all()

print(f"Duplicate base_notice_ids: {len(duplicates)}")
print(f"Total affected records: {sum(d.count for d in duplicates)}")

# Sample some duplicates
for dup in duplicates[:10]:
    print(f"ID: {dup.base_notice_id}, Count: {dup.count}")

db.close()