import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.models.company import OpportunityChain
from pinecone import Pinecone
import os

db = SessionLocal()
pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
index = pc.Index('contracts')

# Get all base_notice_ids from database (regardless of tracking)
all_db_ids = db.query(OpportunityChain.base_notice_id).distinct().all()
db_id_set = {str(row.base_notice_id) for row in all_db_ids}

print(f"📊 Database has {len(db_id_set)} unique base_notice_ids total")
print(f"🔌 Pinecone has 6,868 vectors total")
print(f"   └─ 'contracts' namespace: 6,559")
print(f"   └─ Other namespaces: {6868 - 6559}")
print(f"\n🔍 Discrepancy: {6559 - len(db_id_set)} extra vectors in Pinecone\n")

# Theory: Old contracts that expired/changed quality still in Pinecone
not_live_anymore = db.query(OpportunityChain).filter(
    OpportunityChain.pinecone_id.isnot(None),
    db.or_(
        OpportunityChain.base_description_quality != 'GOOD',
        OpportunityChain.latest_closing_date < db.func.now(),
        OpportunityChain.base_type.in_(['Award Notice', 'Justification'])
    )
).count()

print(f"💀 Contracts in DB with pinecone_id but no longer LIVE/GOOD/BIDDABLE: {not_live_anymore}")

db.close()