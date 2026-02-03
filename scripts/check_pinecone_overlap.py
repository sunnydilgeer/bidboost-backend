# scripts/check_pinecone_overlap.py
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

# Get all base_notice_ids from database that claim to be embedded
db_ids = db.query(OpportunityChain.base_notice_id).filter(
    OpportunityChain.pinecone_id.isnot(None)
).distinct().all()

db_id_set = {str(row.base_notice_id) for row in db_ids}
print(f"Unique base_notice_ids in database: {len(db_id_set)}")

# Sample 100 IDs and check if they exist in Pinecone
sample_ids = list(db_id_set)[:100]
fetch_result = index.fetch(ids=sample_ids, namespace='contracts')
print(f"Sample check: {len(fetch_result.vectors)} out of 100 found in Pinecone")

# Get Pinecone stats
stats = index.describe_index_stats()
print(f"Total vectors in Pinecone: {stats.total_vector_count}")
print(f"Vectors in 'contracts' namespace: {stats.namespaces.get('contracts', {}).get('vector_count', 0)}")

db.close()