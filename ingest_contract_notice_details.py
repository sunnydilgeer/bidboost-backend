"""
SAM.gov Contract Notice Details Ingestion Script
Ingests opportunities from Contract_Notice_Details.csv into Pinecone

Usage:
    python ingest_contract_notice_details.py Contract_Notice_Details.csv [--clear-existing]
"""

import os
import sys
import csv
import hashlib
import argparse
from datetime import datetime
from typing import Generator
import re

from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
from tqdm import tqdm

# Load environment variables from .env file
load_dotenv()

# Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")  # Update with your index name
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"  # 768 dimensions
EMBEDDING_DIMENSIONS = 768
BATCH_SIZE = 100  # Vectors to upsert per batch
EMBEDDING_BATCH_SIZE = 50  # Texts to embed per API call

# Biddable opportunity types (from your analyzer)
BIDDABLE_TYPES = {
    "Combined Synopsis/Solicitation",
    "Solicitation",
}

# Pipeline types (optional - include if you want presolicitations)
PIPELINE_TYPES = {
    "Presolicitation",
    "Sources Sought",
}


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
    """Parse various date formats and return ISO format."""
    if not date_str:
        return ""
    
    # Try common formats
    formats = [
        "%b %d, %Y %I:%M %p UTC",  # "Jan 31, 2025 12:00 PM UTC"
        "%b %d, %Y %H:%M %p UTC",
        "%Y-%m-%d %H:%M:%S.%f%z",  # "2025-12-03 23:19:52.723-05"
        "%Y-%m-%dT%H:%M:%S%z",     # ISO format with timezone
        "%Y-%m-%d",                 # Simple date
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.isoformat()
        except ValueError:
            continue
    
    # Return original if parsing fails
    return date_str


def generate_notice_hash(notice_id: str) -> str:
    """Generate a consistent hash for a notice ID (for Pinecone vector ID)."""
    return hashlib.md5(notice_id.encode()).hexdigest()


def create_embedding_text(row: dict) -> str:
    """Create text for embedding from opportunity data."""
    parts = []
    
    title = row.get("Opportunity Title", "").strip()
    if title:
        parts.append(f"Title: {title}")
    
    description = clean_html(row.get("Description", ""))
    if description:
        # Truncate very long descriptions
        if len(description) > 2000:
            description = description[:2000] + "..."
        parts.append(f"Description: {description}")
    
    agency = row.get("Sub Tier Name", "").strip()
    if agency:
        parts.append(f"Agency: {agency}")
    
    naics = row.get("NAICS", "").strip()
    if naics:
        parts.append(f"NAICS: {naics}")
    
    psc = row.get("PSC", "").strip()
    if psc:
        parts.append(f"PSC: {psc}")
    
    set_aside = row.get("Current Set Aside", "").strip()
    if set_aside:
        parts.append(f"Set-Aside: {set_aside}")
    
    state = row.get("Place of Performance - State", "").strip()
    city = row.get("Place of Performance - City", "").strip()
    if state or city:
        location = ", ".join(filter(None, [city, state]))
        parts.append(f"Location: {location}")
    
    return "\n".join(parts)


def create_metadata(row: dict) -> dict:
    """Create Pinecone metadata from CSV row."""
    notice_id = row.get("Notice ID", "").strip()
    
    return {
        "notice_id": notice_id,
        "title": row.get("Opportunity Title", "").strip(),
        "agency": row.get("Sub Tier Name", "").strip(),
        "office": row.get("Contracting Office", "").strip(),
        "naics_code": row.get("NAICS", "").strip(),
        "psc_code": row.get("PSC", "").strip(),
        "set_aside": row.get("Current Set Aside", "").strip(),
        "state": row.get("Place of Performance - State", "").strip(),
        "city": row.get("Place of Performance - City", "").strip(),
        "response_deadline": parse_date(row.get("Current Response Date", "")),
        "posted_date": parse_date(row.get("Last Published Date", "")),
        "contact_name": row.get("POC Name", "").strip(),
        "contact_email": row.get("POC Email", "").strip(),
        "contract_value": 0,  # Not in new CSV, default to 0
        "description": clean_html(row.get("Description", ""))[:1000],  # Truncate for metadata
        "url": f"https://sam.gov/opp/{notice_id}/view" if notice_id else "",
        "opportunity_type": row.get("Contract Opportunity Type", "").strip(),
        "status": row.get("Status", "").strip(),
    }


def read_csv_opportunities(
    filepath: str, 
    include_pipeline: bool = False
) -> Generator[dict, None, None]:
    """Read and filter opportunities from CSV."""
    
    allowed_types = BIDDABLE_TYPES.copy()
    if include_pipeline:
        allowed_types.update(PIPELINE_TYPES)
    
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            opp_type = row.get("Contract Opportunity Type", "").strip()
            status = row.get("Status", "").strip().lower()
            notice_id = row.get("Notice ID", "").strip()
            
            # Skip if no notice ID
            if not notice_id:
                continue
            
            # Filter by opportunity type
            if opp_type not in allowed_types:
                continue
            
            # Only include active opportunities
            if status != "active":
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
    
    # Get count for specific namespace
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
    
    # Delete all vectors in specified namespace
    index.delete(delete_all=True, namespace=namespace)
    
    print(f"✅ Cleared {total} vectors")
    return total


def main():
    parser = argparse.ArgumentParser(
        description="Ingest SAM.gov Contract Notice Details into Pinecone"
    )
    parser.add_argument("csv_file", help="Path to Contract_Notice_Details.csv")
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
    print("SAM.gov Contract Notice Details Ingestion")
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
    
    print(f"   Found {len(opportunities)} biddable opportunities")
    print()
    
    if len(opportunities) == 0:
        print("❌ No opportunities to process")
        sys.exit(1)
    
    # Prepare data
    print("🔨 Preparing embedding texts and metadata...")
    records = []
    for row in tqdm(opportunities, desc="Preparing"):
        notice_id = row.get("Notice ID", "").strip()
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
        print(f"  Metadata: {records[0]['metadata']}")
        return
    
    # Generate embeddings and upsert in batches
    print("🚀 Generating embeddings and uploading to Pinecone...")
    
    total_uploaded = 0
    for batch in tqdm(
        list(batch_generator(records, BATCH_SIZE)), 
        desc="Uploading batches"
    ):
        # Get embeddings for this batch
        texts = [r["text"] for r in batch]
        
        # Process embeddings in smaller sub-batches
        all_embeddings = []
        for text_batch in batch_generator(texts, EMBEDDING_BATCH_SIZE):
            embeddings = get_embeddings(text_batch, openai_client)
            all_embeddings.extend(embeddings)
        
        # Prepare vectors for upsert
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
    print("✅ INGESTION COMPLETE")
    print("=" * 70)
    print(f"   Total uploaded: {total_uploaded} vectors")
    
    # Show final stats
    stats = index.describe_index_stats()
    print(f"   Index total: {stats.total_vector_count} vectors")
    if args.namespace and args.namespace in stats.namespaces:
        namespace_count = stats.namespaces[args.namespace].vector_count
        print(f"   Namespace '{args.namespace}': {namespace_count} vectors")


if __name__ == "__main__":
    main()