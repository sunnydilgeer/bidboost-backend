"""
SAM.gov Contract Opportunities Ingestion Script (TRUTH LAYER VERSION)
Embeds opportunities from opportunity_chains table (deduplicated, GOOD quality)

Usage:
    python ingest_contract_opportunities.py ContractOpportunitiesFullCSV.csv [--clear-existing] [--namespace contracts]
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime, timezone

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
EMBEDDING_MODEL = "text-embedding-3-small"  # 768 dimensions
EMBEDDING_DIMENSIONS = 768
BATCH_SIZE = 100  # Vectors to upsert per batch
EMBEDDING_BATCH_SIZE = 50  # Texts to embed per API call


# ============================================================
# TRUTH LAYER HELPER FUNCTIONS
# ============================================================

def create_truth_layer_embedding_text(chain: OpportunityChain) -> str:
    """Create embedding text from Truth Layer OpportunityChain."""
    parts = []
    
    # Title
    if chain.base_sol_number:
        parts.append(f"Title: {chain.base_sol_number}")
    
    # Clean description (THIS IS THE GOLD - 76% GOOD quality)
    if chain.base_description:
        desc = chain.base_description[:2000]  # Truncate if needed
        parts.append(f"Description: {desc}")
    
    # Agency
    if chain.base_agency:
        parts.append(f"Agency: {chain.base_agency}")
    
    # NAICS
    if chain.base_naics:
        parts.append(f"NAICS: {chain.base_naics}")
    
    # PSC
    if chain.base_psc:
        parts.append(f"PSC: {chain.base_psc}")
    
    # Set-aside
    if chain.base_set_aside:
        parts.append(f"Set-Aside: {chain.base_set_aside}")
    
    # Location
    if chain.base_city or chain.base_state:
        location = ", ".join(filter(None, [chain.base_city, chain.base_state]))
        parts.append(f"Location: {location}")
    
    # Type
    if chain.base_type:
        parts.append(f"Type: {chain.base_type}")
    
    return "\n".join(parts)


def create_truth_layer_metadata(chain: OpportunityChain) -> dict:
    """Create Pinecone metadata from Truth Layer OpportunityChain."""
    return {
        # IDs
        "notice_id": chain.solicitation_number,
        "opp_id": chain.base_notice_id,
        
        # Content
        "title": chain.base_sol_number[:200] if chain.base_sol_number else "",
        "description": chain.base_description[:1000] if chain.base_description else "",
        
        # Dates
        "response_deadline": chain.latest_closing_date.isoformat() if chain.latest_closing_date else "",
        "posted_date": chain.base_posted_date.isoformat() if chain.base_posted_date else "",
        
        # Organization
        "agency": chain.base_agency or "",
        "office": chain.base_office or "",
        
        # Classification codes
        "naics_code": chain.base_naics or "",
        "psc_code": chain.base_psc or "",
        
        # Set-aside
        "set_aside": chain.base_set_aside or "",
        
        # Location
        "state": chain.base_state or "",
        "city": chain.base_city or "",
        
        # Contact
        "contact_name": chain.base_contact_name or "",
        "contact_email": chain.base_contact_email or "",
        "contact_phone": chain.base_contact_phone or "",
        
        # Type
        "opportunity_type": chain.base_type or "",
        
        # Truth Layer metadata
        "quality": chain.base_description_quality or "UNKNOWN",
        "notice_count": chain.notice_count,
        "has_amendments": chain.has_amendments,
        "source": "truth_layer",  # ← Flag as Truth Layer
        
        # URL
        "url": f"https://sam.gov/opp/{chain.base_notice_id}/view",
        "status": "active",
        
        # Contract value (not in chains yet, default to 0)
        "contract_value": 0,
    }


def get_embeddings(texts: list[str], client: OpenAI) -> list[list[float]]:
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


def clear_index(index, namespace: str = "") -> int:
    """Clear all vectors from the specified namespace."""
    stats = index.describe_index_stats()
    
    if namespace and namespace in stats.namespaces:
        total = stats.namespaces[namespace].vector_count
    elif not namespace:
        total = stats.total_vector_count
    else:
        print(f"Namespace '{namespace}' does not exist or is empty.")
        return 0
    
    if total == 0:
        print(f"Namespace '{namespace}' is already empty.")
        return 0
    
    print(f"Clearing {total} vectors from namespace '{namespace}'...")
    index.delete(delete_all=True, namespace=namespace)
    print(f"✅ Cleared {total} vectors")
    return total


def main():
    parser = argparse.ArgumentParser(
        description="Ingest SAM.gov Contract Opportunities into Pinecone (TRUTH LAYER)"
    )
    parser.add_argument("csv_file", help="Path to ContractOpportunitiesFullCSV.csv")
    parser.add_argument(
        "--clear-existing", 
        action="store_true",
        help="Clear existing vectors before ingesting"
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Pinecone namespace to use (default: contracts)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process data but don't upload to Pinecone"
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip building Truth Layer (assume it's already built)"
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
    print("SAM.gov Contract Opportunities Ingestion (TRUTH LAYER)")
    print("=" * 70)
    print(f"📂 Input: {args.csv_file}")
    print(f"📦 Index: {PINECONE_INDEX_NAME}")
    print(f"🏷️  Namespace: {args.namespace}")
    print()
    
    # ============================================================
    # STEP 1: BUILD TRUTH LAYER FROM CSV (unless --skip-build)
    # ============================================================
    if not args.skip_build:
        print("🔨 Step 1: Building Truth Layer from CSV...")
        result = subprocess.run(
            ["python", "build_contract_truth.py", str(args.csv_file)],
                   )
        
        if result.returncode != 0:
            print(f"❌ Truth Layer build failed:\n{result.stderr}")
            sys.exit(1)
        
        print("✅ Truth Layer built successfully")
        print()
    else:
        print("⏭️  Skipping Truth Layer build (--skip-build)")
        print()
    
    # ============================================================
    # STEP 2: QUERY GOOD QUALITY CONTRACTS FROM TRUTH LAYER
    # ============================================================
    print("📊 Step 2: Fetching LIVE, BIDDABLE, GOOD quality contracts from Truth Layer...")
    db = SessionLocal()

    # Filter for:
    # 1. GOOD quality descriptions
    # 2. Deadline in the future (still open)
    # 3. NOT Award Notices or Justifications (those aren't biddable)
    contracts = db.query(OpportunityChain).filter(
        OpportunityChain.base_description_quality == 'GOOD',
        OpportunityChain.latest_closing_date >= datetime.now(timezone.utc),
        OpportunityChain.base_type.notin_(['Award Notice', 'Justification', 'Justification and Approval (J&A)'])
    ).all()

    print(f"   Found {len(contracts)} LIVE, BIDDABLE, GOOD quality contracts")
    print()

    if len(contracts) == 0:
        print("❌ No LIVE, BIDDABLE, GOOD quality contracts to embed")
        db.close()
        sys.exit(1)
    
    # ============================================================
    # STEP 3: CLEAR OLD EMBEDDINGS (IF REQUESTED)
    # ============================================================
    print("🔌 Connecting to Pinecone and OpenAI...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    
    if args.clear_existing and not args.dry_run:
        clear_index(index, namespace=args.namespace)
        print()
    
    # ============================================================
    # STEP 4: PREPARE EMBEDDINGS FROM TRUTH LAYER
    # ============================================================
    print("🔨 Preparing embedding texts from Truth Layer...")
    records = []
    
    for chain in tqdm(contracts, desc="Preparing"):
        # Create embedding text from clean Truth Layer data
        embedding_text = create_truth_layer_embedding_text(chain)
        metadata = create_truth_layer_metadata(chain)
        
        records.append({
            "id": chain.base_notice_id,  # ← USE base_notice_id as Pinecone ID
            "text": embedding_text,
            "metadata": metadata
        })
    
    print(f"   Prepared {len(records)} records")
    print()
    
    if args.dry_run:
        print("🏃 DRY RUN - Not uploading to Pinecone")
        print("\nSample record:")
        print(f"  ID: {records[0]['id']}")
        print(f"  Text preview: {records[0]['text'][:200]}...")
        print(f"  Metadata:")
        for key, value in records[0]['metadata'].items():
            print(f"    {key}: {value}")
        db.close()
        return
    
    # ============================================================
    # STEP 5: GENERATE EMBEDDINGS AND UPSERT
    # ============================================================
    print("🚀 Generating embeddings and uploading to Pinecone...")
    
    total_uploaded = 0
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
                "id": batch[i]["id"],
                "values": all_embeddings[i],
                "metadata": batch[i]["metadata"]
            }
            for i in range(len(batch))
        ]
        
        # Upsert to Pinecone
        index.upsert(vectors=vectors, namespace=args.namespace)
        total_uploaded += len(vectors)
    
    print()
    print("=" * 70)
    print("✅ INGESTION COMPLETE (TRUTH LAYER)")
    print("=" * 70)
    print(f"   Total uploaded: {total_uploaded} vectors")
    print(f"   Source: opportunity_chains (GOOD quality only)")
    
    stats = index.describe_index_stats()
    print(f"   Index total: {stats.total_vector_count} vectors")
    if args.namespace and args.namespace in stats.namespaces:
        namespace_count = stats.namespaces[args.namespace].vector_count
        print(f"   Namespace '{args.namespace}': {namespace_count} vectors")
    
    db.close()


if __name__ == "__main__":
    main()