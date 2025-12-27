"""
SAM.gov API-Based Contract Ingestion Script
Fetches contracts directly from SAM.gov API with UUIDs for direct links

ADVANTAGES OVER CSV:
- Direct SAM.gov links (uiLink field)
- Actual NAICS codes (not descriptions)
- Automated - no manual CSV download
- Can run daily via cron

FAILSAFES:
- Checkpoint saving on rate limits and errors
- Resume from checkpoint with --resume flag
- Exponential backoff on rate limits (up to 4 minutes)
- Conservative rate limiting (100 per page, 5s delay)
- 5 retries per request

Usage:
    python ingest_sam_api.py --days-back 365 --namespace contracts
    python ingest_sam_api.py --resume                                  # Resume from checkpoint
    python ingest_sam_api.py --days-back 30 --limit 100 --dry-run
"""

import os
import sys
import hashlib
import argparse
import time
import re
from datetime import datetime, timedelta
from typing import Generator, Optional
import json
from pathlib import Path

import requests
from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Configuration
SAM_API_KEY = os.getenv("SAM_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 768
BATCH_SIZE = 100  # Vectors per Pinecone upsert
EMBEDDING_BATCH_SIZE = 50  # Texts per OpenAI call

# CONSERVATIVE RATE LIMIT SETTINGS (to avoid 429 errors)
API_PAGE_SIZE = 100  # Reduced from 1000 to be safer
API_DELAY_SECONDS = 5  # Increased from 2 to be safer
MAX_RETRIES = 5  # Increased from 3

# Checkpoint settings
CHECKPOINT_FILE = "sam_ingestion_checkpoint.json"

# Biddable opportunity types
BIDDABLE_TYPES = {
    "o",  # Solicitation
    "k",  # Combined Synopsis/Solicitation
}

# Include presolicitations if needed
PIPELINE_TYPES = {
    "p",  # Presolicitation
    "r",  # Sources Sought
}

# Type code mapping for reference
TYPE_CODES = {
    "o": "Solicitation",
    "p": "Presolicitation", 
    "k": "Combined Synopsis/Solicitation",
    "r": "Sources Sought",
    "g": "Sale of Surplus Property",
    "s": "Special Notice",
    "i": "Intent to Bundle",
    "a": "Award Notice",
}


# =============================================================================
# CHECKPOINT FUNCTIONS
# =============================================================================

def save_checkpoint(data: dict):
    """Save progress to checkpoint file."""
    data["timestamp"] = datetime.now().isoformat()
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    print(f"   💾 Checkpoint saved: offset={data.get('offset', 0)}, fetched={data.get('total_fetched', 0)}")


def load_checkpoint() -> Optional[dict]:
    """Load checkpoint if exists."""
    if Path(CHECKPOINT_FILE).exists():
        with open(CHECKPOINT_FILE, 'r') as f:
            data = json.load(f)
            print(f"📂 Found checkpoint from {data.get('timestamp', 'unknown')}")
            print(f"   Offset: {data.get('offset', 0)}")
            print(f"   Fetched: {data.get('total_fetched', 0)}")
            print(f"   Uploaded: {data.get('total_uploaded', 0)}")
            return data
    return None


def clear_checkpoint():
    """Remove checkpoint file after successful completion."""
    if Path(CHECKPOINT_FILE).exists():
        os.remove(CHECKPOINT_FILE)
        print("   🗑️  Checkpoint file removed")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def generate_vector_id(notice_id: str) -> str:
    """Generate consistent hash for Pinecone vector ID."""
    return hashlib.md5(notice_id.encode()).hexdigest()


def safe_str(value) -> str:
    """Convert any value to string, None becomes empty string."""
    if value is None:
        return ""
    return str(value)


def fetch_description(description_url: str, api_key: str) -> str:
    """Fetch full description from SAM.gov API."""
    if not description_url:
        return ""
    
    try:
        # Add API key to description URL
        separator = "&" if "?" in description_url else "?"
        url = f"{description_url}{separator}api_key={api_key}"
        
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            # Response might be JSON or plain text
            try:
                data = response.json()
                return clean_html(data.get("description", ""))
            except:
                return clean_html(response.text)
    except Exception as e:
        pass  # Silently fail, description is optional
    
    return ""


# =============================================================================
# API FETCHING WITH FAILSAFES
# =============================================================================

def fetch_contracts_from_api(
    api_key: str,
    posted_from: datetime,
    posted_to: datetime,
    include_pipeline: bool = False,
    limit: Optional[int] = None,
    start_offset: int = 0
) -> Generator[dict, None, None]:
    """
    Fetch contracts from SAM.gov API with pagination and rate limit handling.
    
    Yields individual contract records.
    Supports resuming from a specific offset.
    """
    base_url = "https://api.sam.gov/opportunities/v2/search"
    
    # Determine which types to include
    allowed_types = BIDDABLE_TYPES.copy()
    if include_pipeline:
        allowed_types.update(PIPELINE_TYPES)
    
    # Format dates as MM/DD/YYYY (SAM.gov format)
    from_str = posted_from.strftime("%m/%d/%Y")
    to_str = posted_to.strftime("%m/%d/%Y")
    
    offset = start_offset
    total_fetched = 0
    total_records = None
    consecutive_failures = 0
    
    print(f"📅 Fetching contracts from {from_str} to {to_str}")
    if start_offset > 0:
        print(f"📍 Resuming from offset {start_offset}")
    
    while True:
        params = {
            "api_key": api_key,
            "postedFrom": from_str,
            "postedTo": to_str,
            "limit": API_PAGE_SIZE,
            "offset": offset,
            "ptype": ",".join(allowed_types),
        }
        
        # Retry logic with exponential backoff
        success = False
        response_data = None
        
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(base_url, params=params, timeout=60)
                
                if response.status_code == 429:
                    # Rate limited - wait longer with each retry
                    wait_time = (2 ** attempt) * 30  # 30s, 60s, 120s, 240s, 480s
                    print(f"\n⚠️  Rate limited (429). Waiting {wait_time}s before retry {attempt + 1}/{MAX_RETRIES}...")
                    
                    # Save checkpoint before waiting
                    save_checkpoint({
                        "offset": offset,
                        "total_fetched": total_fetched,
                        "posted_from": from_str,
                        "posted_to": to_str,
                        "status": "rate_limited"
                    })
                    
                    time.sleep(wait_time)
                    continue
                
                if response.status_code == 503:
                    # Service unavailable
                    wait_time = (2 ** attempt) * 30
                    print(f"\n⚠️  Service unavailable (503). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                response_data = response.json()
                success = True
                consecutive_failures = 0
                break
                
            except requests.exceptions.Timeout:
                wait_time = (2 ** attempt) * 15
                print(f"\n⚠️  Timeout. Waiting {wait_time}s before retry {attempt + 1}/{MAX_RETRIES}...")
                time.sleep(wait_time)
                
            except requests.exceptions.RequestException as e:
                wait_time = (2 ** attempt) * 15
                print(f"\n⚠️  Request error: {e}. Waiting {wait_time}s...")
                time.sleep(wait_time)
        
        if not success:
            consecutive_failures += 1
            print(f"\n❌ Failed after {MAX_RETRIES} attempts at offset {offset}")
            
            # Save checkpoint
            save_checkpoint({
                "offset": offset,
                "total_fetched": total_fetched,
                "posted_from": from_str,
                "posted_to": to_str,
                "status": "failed"
            })
            
            if consecutive_failures >= 3:
                print(f"❌ Too many consecutive failures. Stopping.")
                print(f"💡 Run with --resume to continue from offset {offset}")
                return
            
            # Skip this batch and try next
            offset += API_PAGE_SIZE
            time.sleep(60)
            continue
        
        # Get total on first request
        if total_records is None:
            total_records = response_data.get("totalRecords", 0)
            print(f"📊 Total records available: {total_records}")
        
        opportunities = response_data.get("opportunitiesData", [])
        
        if not opportunities:
            print(f"   No more opportunities at offset {offset}")
            break
        
        for opp in opportunities:
            # Only yield active contracts
            if opp.get("active", "").lower() != "yes":
                continue
            
            yield opp
            total_fetched += 1
            
            # Check limit
            if limit and total_fetched >= limit:
                print(f"🛑 Reached limit of {limit} contracts")
                return
        
        offset += len(opportunities)
        
        # Progress update
        pct = (offset / total_records * 100) if total_records else 0
        print(f"   Fetched {offset}/{total_records} ({pct:.1f}%) - {total_fetched} active contracts")
        
        # Check if we've got all records
        if offset >= total_records:
            break
        
        # Rate limit delay
        time.sleep(API_DELAY_SECONDS)
    
    print(f"✅ Finished fetching {total_fetched} active contracts")


# =============================================================================
# EMBEDDING & METADATA (UNCHANGED FROM ORIGINAL)
# =============================================================================

def create_embedding_text(opp: dict, full_description: str = "") -> str:
    """Create text for embedding from API response."""
    parts = []
    
    title = opp.get("title", "")
    if title:
        parts.append(f"Title: {title}")
    
    description = full_description or opp.get("description", "")
    if description and not description.startswith("http"):
        description = clean_html(description)
        if len(description) > 2000:
            description = description[:2000] + "..."
        parts.append(f"Description: {description}")
    
    # Agency info
    agency = opp.get("fullParentPathName", "")
    if agency:
        # Take first part (main agency)
        main_agency = agency.split(".")[0] if "." in agency else agency
        parts.append(f"Agency: {main_agency}")
    
    naics = opp.get("naicsCode", "")
    if naics:
        parts.append(f"NAICS: {naics}")
    
    psc = opp.get("classificationCode", "")
    if psc:
        parts.append(f"PSC: {psc}")
    
    set_aside = opp.get("typeOfSetAsideDescription", "")
    if set_aside:
        parts.append(f"Set-Aside: {set_aside}")
    
    # Location - handle None values
    pop = opp.get("placeOfPerformance") or {}
    state_obj = pop.get("state") if pop else None
    city_obj = pop.get("city") if pop else None
    state = state_obj.get("code", "") if isinstance(state_obj, dict) else ""
    city = city_obj.get("name", "") if isinstance(city_obj, dict) else ""
    if state or city:
        location = ", ".join(filter(None, [city, state]))
        parts.append(f"Location: {location}")
    
    return "\n".join(parts)


def create_metadata(opp: dict, full_description: str = "") -> dict:
    """Create Pinecone metadata from API response."""
    
    # Extract agency name from path
    agency_path = opp.get("fullParentPathName") or ""
    agency = agency_path.split(".")[0] if agency_path else ""
    
    # Get office from path
    path_parts = agency_path.split(".") if agency_path else []
    office = path_parts[-1] if len(path_parts) > 1 else ""
    
    # Place of performance - handle None values safely
    pop = opp.get("placeOfPerformance") or {}
    state_obj = pop.get("state") if pop else None
    city_obj = pop.get("city") if pop else None
    state = state_obj.get("code", "") if isinstance(state_obj, dict) else ""
    city = city_obj.get("name", "") if isinstance(city_obj, dict) else ""
    
    # Office address as fallback for location
    office_addr = opp.get("officeAddress") or {}
    if not state:
        state = office_addr.get("state", "") if office_addr else ""
    if not city:
        city = office_addr.get("city", "") if office_addr else ""
    
    # Point of contact
    contacts = opp.get("pointOfContact") or []
    primary_contact = next((c for c in contacts if c.get("type") == "primary"), contacts[0] if contacts else {})
    if primary_contact is None:
        primary_contact = {}
    
    # Description - use full if fetched, otherwise truncate URL
    description = full_description
    if not description:
        desc_field = opp.get("description") or ""
        if not desc_field.startswith("http"):
            description = clean_html(desc_field)[:1000]
    
    # Build metadata with safe_str to prevent any None values
    return {
        # IDs
        "notice_id": safe_str(opp.get("solicitationNumber")),
        "opportunity_id": safe_str(opp.get("noticeId")),
        
        # Core fields
        "title": safe_str(opp.get("title")),
        "agency": safe_str(agency),
        "office": safe_str(office),
        "description": safe_str(description)[:1000] if description else "",
        
        # Codes - API gives us actual codes!
        "naics_code": safe_str(opp.get("naicsCode")),
        "psc_code": safe_str(opp.get("classificationCode")),
        
        # Set-aside
        "set_aside": safe_str(opp.get("typeOfSetAsideDescription") or opp.get("typeOfSetAside")),
        
        # Location
        "state": safe_str(state),
        "city": safe_str(city),
        
        # Dates
        "posted_date": safe_str(opp.get("postedDate")),
        "response_deadline": safe_str(opp.get("responseDeadLine")),
        
        # Contact - ensure no None values
        "contact_name": safe_str(primary_contact.get("fullName")),
        "contact_email": safe_str(primary_contact.get("email")),
        "contact_phone": safe_str(primary_contact.get("phone")),
        
        # Direct link - this is the key advantage of API!
        "url": safe_str(opp.get("uiLink")),
        
        # Additional
        "opportunity_type": safe_str(TYPE_CODES.get(opp.get("type", ""), opp.get("type", ""))),
        "contract_value": 0,  # Not available in solicitation phase
    }


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


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ingest SAM.gov contracts via API into Pinecone"
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=365,
        help="Fetch contracts posted within this many days (default: 365)"
    )
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
        "--fetch-descriptions",
        action="store_true",
        help="Fetch full descriptions (slower but more complete)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and process but don't upload to Pinecone"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of contracts to process"
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Pinecone namespace (default: contracts)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint"
    )
    
    args = parser.parse_args()
    
    # Validate environment
    if not SAM_API_KEY:
        print("❌ SAM_API_KEY environment variable not set")
        print("   Add to .env: SAM_API_KEY=your-key-here")
        sys.exit(1)
    if not PINECONE_API_KEY:
        print("❌ PINECONE_API_KEY environment variable not set")
        sys.exit(1)
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY environment variable not set")
        sys.exit(1)
    
    print("=" * 70)
    print("SAM.gov API Contract Ingestion (with Failsafes)")
    print("=" * 70)
    print(f"📅 Date range: Last {args.days_back} days")
    print(f"📦 Index: {PINECONE_INDEX_NAME}")
    print(f"🏷️  Namespace: {args.namespace}")
    print(f"🔧 Embedding Model: {EMBEDDING_MODEL}")
    print(f"⏱️  API delay: {API_DELAY_SECONDS}s between calls")
    print(f"📄 Page size: {API_PAGE_SIZE} records per request")
    print()
    
    # Check for checkpoint
    start_offset = 0
    if args.resume:
        checkpoint = load_checkpoint()
        if checkpoint:
            start_offset = checkpoint.get("offset", 0)
            print(f"   Resuming from offset {start_offset}")
        else:
            print("   No checkpoint found, starting fresh")
        print()
    
    # Calculate date range
    posted_to = datetime.now()
    posted_from = posted_to - timedelta(days=args.days_back)
    
    # Initialize clients
    print("🔌 Connecting to Pinecone and OpenAI...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    
    # Clear existing if requested (but not when resuming)
    if args.clear_existing and not args.dry_run and not args.resume:
        print(f"🗑️  Clearing namespace '{args.namespace}'...")
        index.delete(delete_all=True, namespace=args.namespace)
        print("   Done")
        print()
    
    # Fetch contracts from API
    print("🌐 Fetching contracts from SAM.gov API...")
    print()
    
    contracts = list(fetch_contracts_from_api(
        api_key=SAM_API_KEY,
        posted_from=posted_from,
        posted_to=posted_to,
        include_pipeline=args.include_pipeline,
        limit=args.limit,
        start_offset=start_offset
    ))
    
    if not contracts:
        print("❌ No contracts fetched")
        print("💡 If rate limited, wait a few minutes and run with --resume")
        sys.exit(1)
    
    print()
    print(f"📋 Processing {len(contracts)} contracts...")
    
    # Prepare records
    records = []
    
    for opp in tqdm(contracts, desc="Preparing"):
        # Use solicitationNumber as the ID (what CSV calls Notice ID)
        sol_number = opp.get("solicitationNumber", opp.get("noticeId", ""))
        vector_id = generate_vector_id(sol_number)
        
        # Optionally fetch full description
        full_description = ""
        if args.fetch_descriptions:
            desc_url = opp.get("description", "")
            if desc_url.startswith("http"):
                full_description = fetch_description(desc_url, SAM_API_KEY)
        
        embedding_text = create_embedding_text(opp, full_description)
        metadata = create_metadata(opp, full_description)
        
        records.append({
            "id": vector_id,
            "text": embedding_text,
            "metadata": metadata
        })
    
    print(f"   Prepared {len(records)} records")
    
    # Show sample
    if records:
        sample = records[0]
        print()
        print("📄 Sample record:")
        print(f"   Notice ID: {sample['metadata']['notice_id']}")
        print(f"   Title: {sample['metadata']['title'][:60]}...")
        print(f"   NAICS: {sample['metadata']['naics_code']}")
        print(f"   URL: {sample['metadata']['url'][:60]}...")
    
    if args.dry_run:
        print()
        print("🏃 DRY RUN - Not uploading to Pinecone")
        return
    
    # Generate embeddings and upsert
    print()
    print("🚀 Generating embeddings and uploading to Pinecone...")
    
    total_uploaded = 0
    
    for batch in tqdm(list(batch_generator(records, BATCH_SIZE)), desc="Uploading"):
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
    print("✅ INGESTION COMPLETE")
    print("=" * 70)
    print(f"   Total uploaded: {total_uploaded} vectors")
    
    # Final stats
    stats = index.describe_index_stats()
    print(f"   Index total: {stats.total_vector_count} vectors")
    if args.namespace in stats.namespaces:
        ns_count = stats.namespaces[args.namespace].vector_count
        print(f"   Namespace '{args.namespace}': {ns_count} vectors")
    
    # Clear checkpoint on success
    clear_checkpoint()
    
    print()
    print("🎉 Done! Your contracts now have:")
    print("   ✅ Direct SAM.gov links (uiLink)")
    print("   ✅ Actual NAICS codes")
    print("   ✅ No manual CSV download needed")


if __name__ == "__main__":
    main()