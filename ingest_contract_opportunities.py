"""
SAM.gov Contract Opportunities Ingestion Script
Ingests opportunities from ContractOpportunitiesFullCSV.csv into Pinecone

Filters for truly biddable opportunities:
- BaseType: Solicitation or Combined Synopsis/Solicitation
- Active: Yes
- ResponseDeadLine: Present and future
- Type: NOT Award Notice

Usage:
    python ingest_contract_opportunities.py ContractOpportunitiesFullCSV.csv [--clear-existing] [--include-pipeline]
"""

import os
import sys
import csv
import hashlib
import argparse
from datetime import datetime
from typing import Generator
from pathlib import Path
import re

from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
from tqdm import tqdm

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

# Biddable opportunity types
BIDDABLE_TYPES = {
    "Combined Synopsis/Solicitation",
    "Solicitation",
}

# Pipeline types (optional)
PIPELINE_TYPES = {
    "Presolicitation",
    "Sources Sought",
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode common HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_date(date_str: str) -> str:
    """Parse date and return ISO format."""
    if not date_str:
        return ""
    
    try:
        # Simple YYYY-MM-DD format
        dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
        return dt.isoformat()
    except ValueError:
        return date_str


def parse_deadline(date_str: str):
    """Parse deadline to datetime object."""
    if not date_str:
        return None
    
    try:
        return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None


def generate_notice_hash(notice_id: str) -> str:
    """Generate a consistent hash for a notice ID (for Pinecone vector ID)."""
    return hashlib.md5(notice_id.encode()).hexdigest()


def create_sam_gov_url(opp_id: str) -> str:
    """Create direct SAM.gov URL using OPP_ID."""
    if not opp_id:
        return ""
    return f"https://sam.gov/opp/{opp_id}/view"


def create_embedding_text(row: dict) -> str:
    """Create text for embedding from opportunity data."""
    parts = []
    
    title = row.get("Title", "").strip()
    if title:
        parts.append(f"Title: {title}")
    
    description = clean_html(row.get("Description", ""))
    if description:
        if len(description) > 2000:
            description = description[:2000] + "..."
        parts.append(f"Description: {description}")
    
    agency = row.get("Sub-Tier", "").strip()
    if agency:
        parts.append(f"Agency: {agency}")
    
    naics = row.get("NaicsCode", "").strip()
    if naics:
        parts.append(f"NAICS: {naics}")
    
    psc = row.get("ClassificationCode", "").strip()
    if psc:
        parts.append(f"PSC: {psc}")
    
    set_aside = row.get("SetASide", "").strip()
    if set_aside:
        parts.append(f"Set-Aside: {set_aside}")
    
    state = row.get("PopState", "").strip()
    city = row.get("PopCity", "").strip()
    if state or city:
        location = ", ".join(filter(None, [city, state]))
        parts.append(f"Location: {location}")
    
    return "\n".join(parts)


def create_metadata(row: dict) -> dict:
    """Create Pinecone metadata from CSV row."""
    notice_id = row.get("Sol#", "").strip()
    opp_id = row.get("NoticeId", "").strip()
    
    return {
        "notice_id": notice_id,
        "opp_id": opp_id,
        "title": row.get("Title", "").strip(),
        "agency": row.get("Sub-Tier", "").strip(),
        "office": row.get("Office", "").strip(),
        
        # NAICS & PSC
        "naics_code": row.get("NaicsCode", "").strip(),
        "psc_code": row.get("ClassificationCode", "").strip(),
        
        "set_aside": row.get("SetASide", "").strip(),
        "state": row.get("PopState", "").strip(),
        "city": row.get("PopCity", "").strip(),
        "response_deadline": parse_date(row.get("ResponseDeadLine", "")),
        "posted_date": parse_date(row.get("PostedDate", "")),
        "contact_name": row.get("PrimaryContactFullname", "").strip(),
        "contact_email": row.get("PrimaryContactEmail", "").strip(),
        "contract_value": 0,  # Not typically in solicitations
        "description": clean_html(row.get("Description", ""))[:1000],
        
        # Direct SAM.gov URL
        "url": create_sam_gov_url(opp_id),
        
        "opportunity_type": row.get("Type", "").strip(),
        "status": "active",
    }


def read_csv_opportunities(
    filepath: str, 
    include_pipeline: bool = False
) -> Generator[dict, None, None]:
    """Read and filter opportunities from CSV."""
    
    allowed_base_types = BIDDABLE_TYPES.copy()
    if include_pipeline:
        allowed_base_types.update(PIPELINE_TYPES)
    
    now = datetime.now()
    
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            # Extract key fields
            base_type = row.get("BaseType", "").strip()
            opp_type = row.get("Type", "").strip()
            active = row.get("Active", "").strip().lower()
            notice_id = row.get("Sol#", "").strip()
            deadline_str = row.get("ResponseDeadLine", "").strip()
            
            # Filter 1: Must have notice ID
            if not notice_id:
                continue
            
            # Filter 2: Must be biddable base type
            if base_type not in allowed_base_types:
                continue
            
            # Filter 3: Must be active
            if active != "yes":
                continue
            
            # Filter 4: NOT an award notice
            if opp_type == "Award Notice":
                continue
            
            # Filter 5: Must have open deadline (future)
            deadline = parse_deadline(deadline_str)
            if not deadline or deadline <= now:
                continue
            
            yield row


def get_embeddings(texts: list[str], client: OpenAI) -> list[list[float]]:
    """Get embeddings for a batch of texts."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        dimensions=EMBEDDING_DIMENSIONS
    )
    return [item.embedding for item in response.data]


def batch_generator(items: list, batch_size: int) -> Generator[list, None, None]:
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
        description="Ingest SAM.gov Contract Opportunities into Pinecone"
    )
    parser.add_argument("csv_file", help="Path to ContractOpportunitiesFullCSV.csv")
    parser.add_argument(
        "--clear-existing", 
        action="store_true",
        help="Clear existing vectors before ingesting"
    )
    parser.add_argument(
        "--include-pipeline",
        action="store_true",
        help="Include presolicitations and sources sought"
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
        help="Limit number of opportunities to process"
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Pinecone namespace to use (default: contracts)"
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
    print("SAM.gov Contract Opportunities Ingestion")
    print("=" * 70)
    print(f"📂 Input: {args.csv_file}")
    print(f"📦 Index: {PINECONE_INDEX_NAME}")
    print(f"🏷️  Namespace: {args.namespace}")
    print(f"🔧 Embedding Model: {EMBEDDING_MODEL} ({EMBEDDING_DIMENSIONS} dims)")
    print()
    
    # Initialize clients
    print("🔌 Connecting to Pinecone and OpenAI...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    
    # Clear existing if requested
    if args.clear_existing and not args.dry_run:
        clear_index(index, namespace=args.namespace)
        print()
    
    # Read opportunities
    print("📖 Reading opportunities from CSV...")
    opportunities = list(read_csv_opportunities(
        args.csv_file, 
        include_pipeline=args.include_pipeline
    ))
    
    if args.limit:
        opportunities = opportunities[:args.limit]
    
    print(f"   Found {len(opportunities)} open biddable opportunities")
    print()
    
    if len(opportunities) == 0:
        print("❌ No opportunities to process")
        sys.exit(1)
    
    # Prepare data
    print("🔨 Preparing embedding texts and metadata...")
    records = []
    
    for row in tqdm(opportunities, desc="Preparing"):
        notice_id = row.get("Sol#", "").strip()
        vector_id = generate_notice_hash(notice_id)
        embedding_text = create_embedding_text(row)
        metadata = create_metadata(row)
        
        records.append({
            "id": vector_id,
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
        return
    
    # Generate embeddings and upsert in batches
    print("🚀 Generating embeddings and uploading to Pinecone...")
    
    total_uploaded = 0
    for batch in tqdm(
        list(batch_generator(records, BATCH_SIZE)), 
        desc="Uploading batches"
    ):
        texts = [r["text"] for r in batch]
        
        all_embeddings = []
        for text_batch in batch_generator(texts, EMBEDDING_BATCH_SIZE):
            embeddings = get_embeddings(text_batch, openai_client)
            all_embeddings.extend(embeddings)
        
        vectors = [
            {
                "id": batch[i]["id"],
                "values": all_embeddings[i],
                "metadata": batch[i]["metadata"]
            }
            for i in range(len(batch))
        ]
        
        index.upsert(vectors=vectors, namespace=args.namespace)
        total_uploaded += len(vectors)
    
    print()
    print("=" * 70)
    print("✅ INGESTION COMPLETE")
    print("=" * 70)
    print(f"   Total uploaded: {total_uploaded} vectors")
    
    stats = index.describe_index_stats()
    print(f"   Index total: {stats.total_vector_count} vectors")
    if args.namespace and args.namespace in stats.namespaces:
        namespace_count = stats.namespaces[args.namespace].vector_count
        print(f"   Namespace '{args.namespace}': {namespace_count} vectors")


if __name__ == "__main__":
    main()