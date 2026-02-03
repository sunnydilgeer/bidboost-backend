import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.models.company import OpportunityChain
from pinecone import Pinecone
from datetime import datetime, timezone
import os

db = SessionLocal()
pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
index = pc.Index('contracts')

print("=" * 70)
print("PINECONE STALE VECTOR AUDIT")
print("=" * 70)

# Get sample of all IDs from Pinecone (can't fetch all at once)
# We'll use list_paginated to get all IDs
print("\n📥 Fetching all vector IDs from Pinecone...")

all_pinecone_ids = []
for ids in index.list(namespace='contracts'):
    all_pinecone_ids.extend(ids)

print(f"   Found {len(all_pinecone_ids)} vectors in Pinecone 'contracts' namespace\n")

# Check each ID against database in batches
batch_size = 100
not_in_db = []
expired = []
poor_quality = []
award_notices = []
still_good = []

print("🔍 Analyzing vectors...")

for i in range(0, len(all_pinecone_ids), batch_size):
    batch_ids = all_pinecone_ids[i:i+batch_size]
    
    # Query database for these IDs
    contracts = db.query(OpportunityChain).filter(
        OpportunityChain.base_notice_id.in_(batch_ids)
    ).all()
    
    found_ids = {c.base_notice_id for c in contracts}
    
    # IDs not in database at all
    not_in_db.extend([id for id in batch_ids if id not in found_ids])
    
    # Check status of found contracts
    for contract in contracts:
        if contract.latest_closing_date and contract.latest_closing_date < datetime.now(timezone.utc):
            expired.append(contract.base_notice_id)
        elif contract.base_description_quality != 'GOOD':
            poor_quality.append(contract.base_notice_id)
        elif contract.base_type in ['Award Notice', 'Justification']:
            award_notices.append(contract.base_notice_id)
        else:
            still_good.append(contract.base_notice_id)
    
    if (i // batch_size) % 10 == 0:
        print(f"   Processed {min(i + batch_size, len(all_pinecone_ids))}/{len(all_pinecone_ids)}...")

print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70)
print(f"✅ Still LIVE+GOOD+BIDDABLE: {len(still_good)}")
print(f"💀 Expired (past closing date): {len(expired)}")
print(f"📉 POOR/MISSING quality: {len(poor_quality)}")
print(f"🏆 Award Notices/Justifications: {len(award_notices)}")
print(f"❓ Not in database at all: {len(not_in_db)}")
print(f"\n📊 Total: {len(still_good) + len(expired) + len(poor_quality) + len(award_notices) + len(not_in_db)}")
print(f"   Stale vectors: {len(expired) + len(poor_quality) + len(award_notices) + len(not_in_db)}")

# Sample some stale ones
if expired:
    print(f"\n🔬 Sample expired (first 5): {expired[:5]}")
if poor_quality:
    print(f"🔬 Sample poor quality (first 5): {poor_quality[:5]}")

db.close()