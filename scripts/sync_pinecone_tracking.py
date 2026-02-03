import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.models.company import OpportunityChain
from pinecone import Pinecone
import os
from datetime import datetime, timezone

db = SessionLocal()
pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
index = pc.Index('contracts')

# Get all contracts with GOOD quality that should be embedded
contracts = db.query(OpportunityChain).filter(
    OpportunityChain.base_description_quality == 'GOOD',
    OpportunityChain.latest_closing_date >= datetime.now(timezone.utc),
    OpportunityChain.base_type.notin_(['Award Notice', 'Justification'])
).all()

print(f"Checking {len(contracts)} contracts against Pinecone...")

batch_size = 100
updated = 0

for i in range(0, len(contracts), batch_size):
    batch = contracts[i:i+batch_size]
    ids_to_check = [str(c.base_notice_id) for c in batch]
    
    # Check which exist in Pinecone
    fetch_result = index.fetch(ids=ids_to_check, namespace='contracts')
    
    for contract in batch:
        if str(contract.base_notice_id) in fetch_result.vectors:
            # Update database to reflect it's in Pinecone
            contract.pinecone_id = str(contract.base_notice_id)
            if not contract.embedded_at:
                contract.embedded_at = datetime.now(timezone.utc)
            updated += 1
    
    if (i // batch_size) % 10 == 0:
        print(f"Processed {i + len(batch)}/{len(contracts)}...")
        db.commit()

db.commit()
print(f"\n✅ Updated {updated} contracts with existing Pinecone IDs")
print(f"📊 Remaining to embed: {len(contracts) - updated}")

db.close()