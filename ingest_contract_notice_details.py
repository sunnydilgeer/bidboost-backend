"""
SAM.gov Contract Notice Details Ingestion Script
Ingests opportunities from Contract_Notice_Details.csv into Pinecone

UPDATES:
- Added NAICS reverse lookup (description → 6-digit code)
- Fixed SAM.gov URLs to use search instead of broken direct links
- Stores both naics_code and naics_name

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
from pathlib import Path
import re
import json
import urllib.parse

from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
from tqdm import tqdm

# Load environment variables from .env file
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
# NAICS REVERSE LOOKUP
# ============================================================

def load_naics_reverse_lookup() -> dict:
    """
    Load NAICS codes from naics_codes.json and create description → code mapping.
    This allows us to get the 6-digit code from the description in the CSV.
    """
    # Try multiple possible paths for naics_codes.json
    possible_paths = [
        Path(__file__).parent / "app" / "data" / "naics_codes.json",
        Path(__file__).parent / "data" / "naics_codes.json",
        Path(__file__).parent / "naics_codes.json",
        Path("app/data/naics_codes.json"),
        Path("data/naics_codes.json"),
    ]
    
    naics_path = None
    for path in possible_paths:
        if path.exists():
            naics_path = path
            break
    
    if not naics_path:
        print("⚠️  naics_codes.json not found, NAICS codes will not be resolved")
        print("   Searched paths:", [str(p) for p in possible_paths])
        return {}
    
    try:
        with open(naics_path, 'r') as f:
            naics_codes = json.load(f)  # {"541519": "Other Computer Related Services", ...}
        
        # Create reverse lookup: description (lowercase) → code
        reverse = {}
        for code, description in naics_codes.items():
            if description:
                reverse[description.lower().strip()] = code
        
        print(f"✅ Loaded {len(reverse)} NAICS codes from {naics_path}")
        return reverse
        
    except Exception as e:
        print(f"⚠️  Failed to load naics_codes.json: {e}")
        return {}


def get_naics_code_from_description(description: str, reverse_lookup: dict) -> str:
    """
    Look up NAICS 6-digit code from description.
    
    Args:
        description: NAICS description from CSV (e.g., "Other Computer Related Services")
        reverse_lookup: Dict mapping lowercase descriptions to codes
        
    Returns:
        6-digit NAICS code (e.g., "541519") or empty string if not found
    """
    if not description or not reverse_lookup:
        return ""
    
    desc_lower = description.lower().strip()
    
    # Exact match
    if desc_lower in reverse_lookup:
        return reverse_lookup[desc_lower]
    
    # Partial match (CSV descriptions might be truncated)
    for full_desc, code in reverse_lookup.items():
        # Check if one contains the other
        if desc_lower in full_desc or full_desc in desc_lower:
            return code
        
        # Check if first 50 chars match (handles truncation)
        if len(desc_lower) > 20 and len(full_desc) > 20:
            if desc_lower[:50] == full_desc[:50]:
                return code
    
    return ""  # No match found


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
    """Parse various date formats and return ISO format."""
    if not date_str:
        return ""
    
    formats = [
        "%b %d, %Y %I:%M %p UTC",
        "%b %d, %Y %H:%M %p UTC",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.isoformat()
        except ValueError:
            continue
    
    return date_str


def generate_notice_hash(notice_id: str) -> str:
    """Generate a consistent hash for a notice ID (for Pinecone vector ID)."""
    return hashlib.md5(notice_id.encode()).hexdigest()


def create_sam_gov_url(notice_id: str) -> str:
    """
    Create a working SAM.gov URL for a contract.
    
    Direct links like sam.gov/opp/{notice_id}/view don't work because
    SAM.gov uses internal UUIDs, not Notice IDs. Instead, we create
    a search URL that finds the contract by its Notice ID.
    """
    if not notice_id:
        return ""
    
    # URL-encode the notice ID for safety
    encoded_id = urllib.parse.quote(notice_id, safe='')
    
    # Use SAM.gov search with the notice ID as keyword
    return f"https://sam.gov/search/?keywords={encoded_id}&sort=-modifiedDate&index=opp&is_active=true"


def create_embedding_text(row: dict) -> str:
    """Create text for embedding from opportunity data."""
    parts = []
    
    title = row.get("Opportunity Title", "").strip()
    if title:
        parts.append(f"Title: {title}")
    
    description = clean_html(row.get("Description", ""))
    if description:
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


def create_metadata(row: dict, naics_reverse_lookup: dict) -> dict:
    """
    Create Pinecone metadata from CSV row.
    
    Args:
        row: CSV row dict
        naics_reverse_lookup: Dict for looking up NAICS codes from descriptions
    """
    notice_id = row.get("Notice ID", "").strip()
    
    # Get NAICS description from CSV
    naics_description = row.get("NAICS", "").strip()
    
    # Look up the 6-digit code from the description
    naics_code = get_naics_code_from_description(naics_description, naics_reverse_lookup)
    
    # Log if we couldn't find a code (helps identify missing mappings)
    if naics_description and not naics_code:
        # Only log unique missing codes (avoid spam)
        pass  # Could add logging here if needed
    
    return {
        "notice_id": notice_id,
        "title": row.get("Opportunity Title", "").strip(),
        "agency": row.get("Sub Tier Name", "").strip(),
        "office": row.get("Contracting Office", "").strip(),
        
        # NAICS: Now stores both code and name
        "naics_code": naics_code,  # 6-digit code like "541519"
        "naics_name": naics_description,  # Full description
        
        # PSC code (keeping as-is since PSC column has descriptions too)
        "psc_code": row.get("PSC", "").strip(),
        
        "set_aside": row.get("Current Set Aside", "").strip(),
        "state": row.get("Place of Performance - State", "").strip(),
        "city": row.get("Place of Performance - City", "").strip(),
        "response_deadline": parse_date(row.get("Current Response Date", "")),
        "posted_date": parse_date(row.get("Last Published Date", "")),
        "contact_name": row.get("POC Name", "").strip(),
        "contact_email": row.get("POC Email", "").strip(),
        "contract_value": 0,
        "description": clean_html(row.get("Description", ""))[:1000],
        
        # URL: Now uses search URL that actually works
        "url": create_sam_gov_url(notice_id),
        
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
            
            if not notice_id:
                continue
            
            if opp_type not in allowed_types:
                continue
            
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
    
    # Load NAICS reverse lookup
    print("📖 Loading NAICS code mappings...")
    naics_reverse_lookup = load_naics_reverse_lookup()
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
    naics_found = 0
    naics_missing = 0
    missing_naics_descriptions = set()
    
    for row in tqdm(opportunities, desc="Preparing"):
        notice_id = row.get("Notice ID", "").strip()
        vector_id = generate_notice_hash(notice_id)
        embedding_text = create_embedding_text(row)
        metadata = create_metadata(row, naics_reverse_lookup)
        
        # Track NAICS lookup success
        if metadata["naics_code"]:
            naics_found += 1
        elif metadata["naics_name"]:
            naics_missing += 1
            missing_naics_descriptions.add(metadata["naics_name"])
        
        records.append({
            "id": vector_id,
            "text": embedding_text,
            "metadata": metadata
        })
    
    print(f"   Prepared {len(records)} records")
    print(f"   NAICS codes found: {naics_found}")
    print(f"   NAICS codes missing: {naics_missing}")
    
    if missing_naics_descriptions and len(missing_naics_descriptions) <= 10:
        print(f"   Missing NAICS mappings for:")
        for desc in list(missing_naics_descriptions)[:10]:
            print(f"      - {desc[:60]}...")
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
    print(f"   NAICS codes resolved: {naics_found}/{naics_found + naics_missing}")
    
    stats = index.describe_index_stats()
    print(f"   Index total: {stats.total_vector_count} vectors")
    if args.namespace and args.namespace in stats.namespaces:
        namespace_count = stats.namespaces[args.namespace].vector_count
        print(f"   Namespace '{args.namespace}': {namespace_count} vectors")


if __name__ == "__main__":
    main()