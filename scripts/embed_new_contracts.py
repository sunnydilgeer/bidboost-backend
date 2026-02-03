"""
Embed New Contracts to Pinecone (Incremental)
Extracts embedding logic from ingest_contract_opportunities.py

KEY DIFFERENCES:
- Only embeds contracts where pinecone_id IS NULL (not already embedded)
- Updates database with pinecone_id AND embedded_at after success
- No CSV processing (works directly with opportunity_chains table)
- Skips contracts with POOR/MISSING quality (already filtered by Truth Layer)

Usage:
    python scripts/embed_new_contracts.py
    python scripts/embed_new_contracts.py --limit 100 --dry-run
    python scripts/embed_new_contracts.py --date-from 2026-02-01
"""

import os
import sys
import argparse
from datetime import datetime, timezone
from typing import List

from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
from tqdm import tqdm

from app.database import SessionLocal
from app.models.company import OpportunityChain

# Load environment variables
load_dotenv()

# Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 768
BATCH_SIZE = 100
EMBEDDING_BATCH_SIZE = 50


def create_truth_layer_embedding_text(chain: OpportunityChain) -> str:
    """Create embedding text from Truth Layer OpportunityChain."""
    parts = []
    
    if chain.base_sol_number:
        parts.append(f"Title: {chain.base_sol_number}")
    
    if chain.base_description:
        desc = chain.base_description[:2000]
        parts.append(f"Description: {desc}")
    
    if chain.base_agency:
        parts.append(f"Agency: {chain.base_agency}")
    
    if chain.base_naics:
        parts.append(f"NAICS: {chain.base_naics}")
    
    if chain.base_psc:
        parts.append(f"PSC: {chain.base_psc}")
    
    if chain.base_set_aside:
        parts.append(f"Set-Aside: {chain.base_set_aside}")
    
    if chain.base_city or chain.base_state:
        location = ", ".join(filter(None, [chain.base_city, chain.base_state]))
        parts.append(f"Location: {location}")
    
    if chain.base_type:
        parts.append(f"Type: {chain.base_type}")
    
    return "\n".join(parts)


def create_truth_layer_metadata(chain: OpportunityChain) -> dict:
    """Create Pinecone metadata from Truth Layer OpportunityChain."""
    return {
        "notice_id": chain.solicitation_number,
        "opp_id": chain.base_notice_id,
        "title": chain.base_sol_number[:200] if chain.base_sol_number else "",
        "description": chain.base_description[:1000] if chain.base_description else "",
        "response_deadline": chain.latest_closing_date.isoformat() if chain.latest_closing_date else "",
        "posted_date": chain.base_posted_date.isoformat() if chain.base_posted_date else "",
        "agency": chain.base_agency or "",
        "office": chain.base_office or "",
        "naics_code": chain.base_naics or "",
        "psc_code": chain.base_psc or "",
        "set_aside": chain.base_set_aside or "",
        "state": chain.base_state or "",
        "city": chain.base_city or "",
        "contact_name": chain.base_contact_name or "",
        "contact_email": chain.base_contact_email or "",
        "contact_phone": chain.base_contact_phone or "",
        "opportunity_type": chain.base_type or "",
        "quality": chain.base_description_quality or "UNKNOWN",
        "notice_count": chain.notice_count,
        "has_amendments": chain.has_amendments,
        "source": "truth_layer",
        "url": f"https://sam.gov/opp/{chain.base_notice_id}/view",
        "status": "active",
        "contract_value": 0,
    }


def get_embeddings(texts: List[str], client: OpenAI) -> List[List[float]]:
    """Get embeddings for a batch of texts."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        dimensions=EMBEDDING_DIMENSIONS
    )
    return [item.embedding for item in response.data]


def batch_generator(items: list, batch_size: int):
    """Yield batches of items."""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def main():
    parser = argparse.ArgumentParser(
        description="Embed new contracts to Pinecone (incremental)"
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Pinecone namespace (default: contracts)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process data but don't upload to Pinecone"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of contracts to embed (for testing)"
    )
    parser.add_argument(
        "--date-from",
        type=str,
        default=None,
        help="Only embed contracts created after this date (YYYY-MM-DD)"
    )
    
    args = parser.parse_args()
    
    # Validate environment
    if not PINECONE_API_KEY:
        print("❌ PINECONE_API_KEY environment variable not set")
        sys.exit(1)
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY environment variable not set")
        sys.exit(1)
    
    print("=" * 70)
    print("EMBED NEW CONTRACTS (INCREMENTAL)")
    print("=" * 70)
    print(f"📦 Index: {PINECONE_INDEX_NAME}")
    print(f"🏷️  Namespace: {args.namespace}")
    if args.limit:
        print(f"🔬 Limit: {args.limit} contracts")
    if args.date_from:
        print(f"📅 Date filter: >= {args.date_from}")
    print()
    
    # ============================================================
    # STEP 1: QUERY CONTRACTS NEEDING EMBEDDING
    # ============================================================
    print("🔍 Finding contracts needing embedding...")
    db = SessionLocal()

    query = db.query(OpportunityChain).filter(
        OpportunityChain.pinecone_id.is_(None),
        OpportunityChain.base_description_quality == 'GOOD',
        OpportunityChain.latest_closing_date >= datetime.now(timezone.utc),
        OpportunityChain.base_type.notin_(['Award Notice', 'Justification', 'Justification and Approval (J&A)'])
    )
    
    # Optional date filter
    if args.date_from:
        date_from = datetime.fromisoformat(args.date_from).replace(tzinfo=timezone.utc)
        query = query.filter(OpportunityChain.created_at >= date_from)
    
    # Optional limit
    if args.limit:
        query = query.limit(args.limit)
    
    contracts = query.all()

    print(f"   Found {len(contracts)} contracts needing embedding")
    print()

    if len(contracts) == 0:
        print("✅ No contracts to embed - all up to date!")
        db.close()
        return
    
    # ============================================================
    # STEP 2: CONNECT TO PINECONE AND OPENAI
    # ============================================================
    if not args.dry_run:
        print("🔌 Connecting to Pinecone and OpenAI...")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(PINECONE_INDEX_NAME)
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        print()
    
    # ============================================================
    # STEP 3: PREPARE EMBEDDINGS
    # ============================================================
    print("🔨 Preparing embedding texts...")
    records = []
    
    for chain in tqdm(contracts, desc="Preparing"):
        embedding_text = create_truth_layer_embedding_text(chain)
        metadata = create_truth_layer_metadata(chain)
        
        records.append({
            "chain_id": chain.id,
            "pinecone_id": chain.base_notice_id,
            "text": embedding_text,
            "metadata": metadata
        })
    
    print(f"   Prepared {len(records)} records")
    print()
    
    if args.dry_run:
        print("🏃 DRY RUN - Not uploading to Pinecone")
        print("\nSample record:")
        print(f"  DB ID: {records[0]['chain_id']}")
        print(f"  Pinecone ID: {records[0]['pinecone_id']}")
        print(f"  Text preview: {records[0]['text'][:200]}...")
        db.close()
        return
    
    # ============================================================
    # STEP 4: GENERATE EMBEDDINGS AND UPSERT
    # ============================================================
    print("🚀 Generating embeddings and uploading to Pinecone...")
    
    total_uploaded = 0
    now = datetime.now(timezone.utc)
    
    for batch in tqdm(
        list(batch_generator(records, BATCH_SIZE)), 
        desc="Uploading batches"
    ):
        texts = [r["text"] for r in batch]
        
        # Get embeddings in sub-batches
        all_embeddings = []
        for text_batch in batch_generator(texts, EMBEDDING_BATCH_SIZE):
            embeddings = get_embeddings(text_batch, openai_client)
            all_embeddings.extend(embeddings)
        
        # Prepare vectors
        vectors = [
            {
                "id": batch[i]["pinecone_id"],
                "values": all_embeddings[i],
                "metadata": batch[i]["metadata"]
            }
            for i in range(len(batch))
        ]
        
        # Upsert to Pinecone
        index.upsert(vectors=vectors, namespace=args.namespace)
        total_uploaded += len(vectors)
        
        # Update database
        for record in batch:
            db.query(OpportunityChain).filter(
                OpportunityChain.id == record["chain_id"]
            ).update({
                "pinecone_id": record["pinecone_id"],
                "embedded_at": now
            })
        
        db.commit()
    
    print()
    print("=" * 70)
    print("✅ EMBEDDING COMPLETE")
    print("=" * 70)
    print(f"   Total embedded: {total_uploaded} vectors")
    print(f"   Database updated: {total_uploaded} records")
    print(f"   Timestamp: {now.isoformat()}")
    
    # Verify Pinecone stats
    stats = index.describe_index_stats()
    print(f"   Index total: {stats.total_vector_count} vectors")
    if args.namespace and args.namespace in stats.namespaces:
        namespace_count = stats.namespaces[args.namespace].vector_count
        print(f"   Namespace '{args.namespace}': {namespace_count} vectors")
    
    db.close()


if __name__ == "__main__":
    main()