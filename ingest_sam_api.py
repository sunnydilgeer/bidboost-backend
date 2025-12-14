"""
SAM.gov API-Based Contract Ingestion Script
Fetches contracts directly from SAM.gov API with UUIDs for direct links

ADVANTAGES OVER CSV:
- Direct SAM.gov links (uiLink field)
- Actual NAICS codes (not descriptions)
- Automated - no manual CSV download
- Can run daily via cron

RATE LIMITING:
- Uses 1000 records per request (API max)
- 2-second delay between requests
- Retry with exponential backoff on rate limit errors
- 20k contracts = ~20 API calls = ~1 minute

Usage:
    python ingest_sam_api.py --days-back 365 --namespace contracts
    python ingest_sam_api.py --days-back 30 --namespace contracts --dry-run
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
API_PAGE_SIZE = 1000  # Max allowed by SAM.gov API
API_DELAY_SECONDS = 2  # Delay between API calls
MAX_RETRIES = 3

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


def fetch_contracts_from_api(
    api_key: str,
    posted_from: datetime,
    posted_to: datetime,
    include_pipeline: bool = False,
    limit: Optional[int] = None
) -> Generator[dict, None, None]:
    """
    Fetch contracts from SAM.gov API with pagination.
    
    Yields individual contract records.
    """
    base_url = "https://api.sam.gov/opportunities/v2/search"
    
    # Determine which types to include
    allowed_types = BIDDABLE_TYPES.copy()
    if include_pipeline:
        allowed_types.update(PIPELINE_TYPES)
    
    # Format dates as MM/DD/YYYY (SAM.gov format)
    from_str = posted_from.strftime("%m/%d/%Y")
    to_str = posted_to.strftime("%m/%d/%Y")
    
    offset = 0
    total_fetched = 0
    total_records = None
    
    print(f"📅 Fetching contracts from {from_str} to {to_str}")
    
    while True:
        params = {
            "api_key": api_key,
            "postedFrom": from_str,
            "postedTo": to_str,
            "limit": API_PAGE_SIZE,
            "offset": offset,
            "ptype": ",".join(allowed_types),  # Filter by opportunity type
        }
        
        # Retry logic with exponential backoff
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(base_url, params=params, timeout=30)
                
                if response.status_code == 429:
                    # Rate limited - wait and retry
                    wait_time = (2 ** attempt) * 5  # 5s, 10s, 20s
                    print(f"⚠️  Rate limited. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                break
                
            except requests.exceptions.RequestException as e:
                if attempt == MAX_RETRIES - 1:
                    print(f"❌ API request failed after {MAX_RETRIES} attempts: {e}")
                    return
                time.sleep(2 ** attempt)
        
        data = response.json()
        
        # Get total on first request
        if total_records is None:
            total_records = data.get("totalRecords", 0)
            print(f"📊 Total records available: {total_records}")
        
        opportunities = data.get("opportunitiesData", [])
        
        if not opportunities:
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
        print(f"   Fetched {offset}/{total_records} records...")
        
        # Check if we've got all records
        if offset >= total_records:
            break
        
        # Rate limit delay
        time.sleep(API_DELAY_SECONDS)
    
    print(f"✅ Fetched {total_fetched} active contracts")


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
    
    # Location
    pop = opp.get("placeOfPerformance", {})
    state = pop.get("state", {}).get("code", "")
    city = pop.get("city", {}).get("name", "")
    if state or city:
        location = ", ".join(filter(None, [city, state]))
        parts.append(f"Location: {location}")
    
    return "\n".join(parts)


def create_metadata(opp: dict, full_description: str = "") -> dict:
    """Create Pinecone metadata from API response."""
    
    # Extract agency name from path
    agency_path = opp.get("fullParentPathName", "")
    agency = agency_path.split(".")[0] if agency_path else ""
    
    # Get office from path
    path_parts = agency_path.split(".") if agency_path else []
    office = path_parts[-1] if len(path_parts) > 1 else ""
    
    # Place of performance
    pop = opp.get("placeOfPerformance", {})
    state = pop.get("state", {}).get("code", "") if isinstance(pop.get("state"), dict) else ""
    city = pop.get("city", {}).get("name", "") if isinstance(pop.get("city"), dict) else ""
    
    # Office address as fallback for location
    office_addr = opp.get("officeAddress", {})
    if not state:
        state = office_addr.get("state", "")
    if not city:
        city = office_addr.get("city", "")
    
    # Point of contact
    contacts = opp.get("pointOfContact", [])
    primary_contact = next((c for c in contacts if c.get("type") == "primary"), contacts[0] if contacts else {})
    
    # Description - use full if fetched, otherwise truncate URL
    description = full_description
    if not description:
        desc_field = opp.get("description", "")
        if not desc_field.startswith("http"):
            description = clean_html(desc_field)[:1000]
    
    return {
        # IDs
        "notice_id": opp.get("solicitationNumber", ""),  # Human-readable ID
        "opportunity_id": opp.get("noticeId", ""),  # UUID for direct link
        
        # Core fields
        "title": opp.get("title", ""),
        "agency": agency,
        "office": office,
        "description": description[:1000] if description else "",
        
        # Codes - API gives us actual codes!
        "naics_code": opp.get("naicsCode", ""),
        "psc_code": opp.get("classificationCode", ""),
        
        # Set-aside
        "set_aside": opp.get("typeOfSetAsideDescription", "") or opp.get("typeOfSetAside", "") or "",
        
        # Location
        "state": state,
        "city": city,
        
        # Dates
        "posted_date": opp.get("postedDate", ""),
        "response_deadline": opp.get("responseDeadLine", ""),
        
        # Contact
        "contact_name": primary_contact.get("fullName", ""),
        "contact_email": primary_contact.get("email", ""),
        "contact_phone": primary_contact.get("phone", ""),
        
        # Direct link - this is the key advantage of API!
        "url": opp.get("uiLink", ""),
        
        # Additional
        "opportunity_type": TYPE_CODES.get(opp.get("type", ""), opp.get("type", "")),
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
    print("SAM.gov API Contract Ingestion")
    print("=" * 70)
    print(f"📅 Date range: Last {args.days_back} days")
    print(f"📦 Index: {PINECONE_INDEX_NAME}")
    print(f"🏷️  Namespace: {args.namespace}")
    print(f"🔧 Embedding Model: {EMBEDDING_MODEL}")
    print()
    
    # Calculate date range
    posted_to = datetime.now()
    posted_from = posted_to - timedelta(days=args.days_back)
    
    # Initialize clients
    print("🔌 Connecting to Pinecone and OpenAI...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    
    # Clear existing if requested
    if args.clear_existing and not args.dry_run:
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
        limit=args.limit
    ))
    
    if not contracts:
        print("❌ No contracts fetched")
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
    
    print()
    print("🎉 Done! Your contracts now have:")
    print("   ✅ Direct SAM.gov links (uiLink)")
    print("   ✅ Actual NAICS codes")
    print("   ✅ No manual CSV download needed")


if __name__ == "__main__":
    main()