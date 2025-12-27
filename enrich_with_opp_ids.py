"""
SAM.gov Opportunity ID Enrichment Script
Enriches existing Pinecone contract vectors with opp_id from ContractOpportunitiesFullCSV.csv

This script:
1. Loads ContractOpportunitiesFullCSV.csv to build a solicitation → opp_id lookup
2. Fetches existing vectors from Pinecone in batches
3. Matches vectors to opp_id using normalized solicitation numbers
4. Updates metadata with opp_id field
5. Upserts enriched vectors back to Pinecone

Usage:
    python enrich_with_opp_ids.py ContractOpportunitiesFullCSV.csv [--namespace contracts]
"""

import os
import sys
import csv
import hashlib
import argparse
import re
from typing import Generator
from pathlib import Path

from dotenv import load_dotenv
from pinecone import Pinecone
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")
BATCH_SIZE = 100  # Vectors to fetch/upsert per batch


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def normalize_solicitation_number(sol_number: str) -> str:
    """
    Normalize solicitation number for matching.
    
    Handles format variations like:
    - W50S91-26-Q-A002 → W50S9126QA002
    - PAN409-26-P-0000-026834 → PAN40926P0000026834
    
    Args:
        sol_number: Raw solicitation number from CSV
        
    Returns:
        Normalized solicitation number (uppercase, alphanumeric only)
    """
    if not sol_number:
        return ""
    
    # Uppercase and remove all non-alphanumeric characters
    normalized = re.sub(r'[^A-Z0-9]', '', sol_number.upper().strip())
    return normalized


def build_opp_id_lookup(csv_filepath: str) -> dict:
    """
    Build a lookup table: normalized_solicitation_number → opp_id
    
    Args:
        csv_filepath: Path to ContractOpportunitiesFullCSV.csv
        
    Returns:
        Dict mapping normalized solicitation numbers to 32-hex opp_ids
    """
    lookup = {}
    total_rows = 0
    valid_mappings = 0
    
    print("📖 Loading ContractOpportunitiesFullCSV.csv...")
    
    with open(csv_filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            total_rows += 1
            
            # Extract NoticeId (32-hex opp_id) and Sol# (solicitation number)
            opp_id = row.get("NoticeId", "").strip()
            sol_number = row.get("Sol#", "").strip()
            
            # Skip if either is missing
            if not opp_id or not sol_number:
                continue
            
            # Validate opp_id format (should be 32 hex characters)
            if not re.match(r'^[a-f0-9]{32}$', opp_id.lower()):
                continue
            
            # Normalize solicitation number
            normalized_sol = normalize_solicitation_number(sol_number)
            
            if normalized_sol:
                lookup[normalized_sol] = opp_id
                valid_mappings += 1
    
    print(f"   Total rows processed: {total_rows}")
    print(f"   Valid opp_id mappings: {valid_mappings}")
    print()
    
    return lookup


def generate_notice_hash(notice_id: str) -> str:
    """Generate consistent hash for notice ID (matches ingestion script)."""
    return hashlib.md5(notice_id.encode()).hexdigest()


def fetch_all_vectors(index, namespace: str = "") -> list:
    """
    Fetch all vectors from Pinecone index (Pinecone v8 compatible).
    Uses query-based scanning to get all vectors.
    
    Args:
        index: Pinecone index object
        namespace: Namespace to fetch from
        
    Returns:
        List of vector objects with id, metadata, and values
    """
    print(f"🔍 Fetching vectors from namespace '{namespace}'...")
    
    # Get index stats
    stats = index.describe_index_stats()
    if namespace and namespace in stats.namespaces:
        total_count = stats.namespaces[namespace].vector_count
    else:
        total_count = stats.total_vector_count
    
    dimension = stats.dimension
    
    print(f"   Expected vectors: {total_count}")
    print(f"   Vector dimension: {dimension}")
    
    # Use query-based approach to scan all vectors
    # Query with dummy vector and high top_k
    all_vectors_dict = {}  # Use dict to avoid duplicates
    
    try:
        # Create multiple diverse dummy vectors to scan different parts of the space
        # More vectors = better coverage of the embedding space
        dummy_vectors = [
            [0.0] * dimension,                    # All zeros
            [1.0] * dimension,                    # All ones
            [-1.0] * dimension,                   # All negative ones
            [0.5] * dimension,                    # Half values
            [-0.5] * dimension,                   # Negative half
            [0.1] * dimension,                    # Small positive
            [-0.1] * dimension,                   # Small negative
            [i % 2 for i in range(dimension)],    # Alternating 0,1
            [i % 3 - 1 for i in range(dimension)], # Alternating -1,0,1
            [(i % 5) / 5.0 for i in range(dimension)], # Pattern 0, 0.2, 0.4, 0.6, 0.8
        ]
        
        for idx, dummy_vector in enumerate(dummy_vectors):
            print(f"   Scanning with vector {idx+1}/{len(dummy_vectors)}...", end=' ')
            
            # Query in batches (max top_k is 10000)
            top_k = min(10000, total_count)
            
            result = index.query(
                vector=dummy_vector,
                top_k=top_k,
                namespace=namespace,
                include_metadata=True,
                include_values=True
            )
            
            new_count = 0
            for match in result.matches:
                if match.id not in all_vectors_dict:
                    all_vectors_dict[match.id] = {
                        'id': match.id,
                        'values': match.values,
                        'metadata': match.metadata or {}
                    }
                    new_count += 1
            
            print(f"Added {new_count} new vectors (total: {len(all_vectors_dict)})")
            
            # If we've found all vectors, stop early
            if len(all_vectors_dict) >= total_count:
                print(f"   ✓ Found all {total_count} vectors!")
                break
        
    except Exception as e:
        print(f"   Error during query scan: {e}")
        import traceback
        traceback.print_exc()
    
    all_vectors = list(all_vectors_dict.values())
    
    print(f"   Successfully fetched {len(all_vectors)} vectors with metadata")
    print()
    
    return all_vectors


def enrich_vectors_with_opp_id(
    vectors: list,
    opp_id_lookup: dict
) -> tuple[list, dict]:
    """
    Enrich vectors with opp_id by matching solicitation numbers.
    
    Args:
        vectors: List of vector dicts with id, values, metadata
        opp_id_lookup: Dict mapping normalized solicitation → opp_id
        
    Returns:
        Tuple of (enriched_vectors, stats_dict)
    """
    print("🔨 Enriching vectors with opp_id...")
    
    enriched = []
    stats = {
        'total': len(vectors),
        'matched': 0,
        'already_had_opp_id': 0,
        'no_solicitation_number': 0,
        'not_found_in_lookup': 0,
        'updated': 0
    }
    
    for vector in tqdm(vectors, desc="Processing vectors"):
        metadata = vector['metadata']
        
        # Check if already has opp_id
        if 'opp_id' in metadata and metadata['opp_id']:
            stats['already_had_opp_id'] += 1
            enriched.append(vector)
            continue
        
        # Get solicitation number (could be in notice_id or solicitation_number field)
        sol_number = metadata.get('notice_id', '')
        if not sol_number:
            sol_number = metadata.get('solicitation_number', '')
        
        if not sol_number:
            stats['no_solicitation_number'] += 1
            enriched.append(vector)
            continue
        
        # Normalize and lookup
        normalized_sol = normalize_solicitation_number(sol_number)
        opp_id = opp_id_lookup.get(normalized_sol)
        
        if opp_id:
            # Add opp_id to metadata
            metadata['opp_id'] = opp_id
            stats['matched'] += 1
            stats['updated'] += 1
        else:
            stats['not_found_in_lookup'] += 1
        
        enriched.append(vector)
    
    print()
    print("📊 Enrichment Statistics:")
    print(f"   Total vectors: {stats['total']}")
    print(f"   Already had opp_id: {stats['already_had_opp_id']}")
    print(f"   Successfully matched: {stats['matched']}")
    print(f"   Not found in lookup: {stats['not_found_in_lookup']}")
    print(f"   No solicitation number: {stats['no_solicitation_number']}")
    print(f"   Vectors updated: {stats['updated']}")
    print()
    
    return enriched, stats


def upsert_enriched_vectors(
    index,
    vectors: list,
    namespace: str = ""
) -> int:
    """
    Upsert enriched vectors back to Pinecone.
    
    Args:
        index: Pinecone index object
        vectors: List of enriched vectors
        namespace: Namespace to upsert to
        
    Returns:
        Total number of vectors upserted
    """
    print("🚀 Uploading enriched vectors to Pinecone...")
    
    total_uploaded = 0
    
    for i in tqdm(range(0, len(vectors), BATCH_SIZE), desc="Uploading batches"):
        batch = vectors[i:i + BATCH_SIZE]
        
        # Format for Pinecone upsert
        upsert_vectors = [
            {
                'id': v['id'],
                'values': v['values'],
                'metadata': v['metadata']
            }
            for v in batch
        ]
        
        index.upsert(vectors=upsert_vectors, namespace=namespace)
        total_uploaded += len(upsert_vectors)
    
    print()
    return total_uploaded


def main():
    parser = argparse.ArgumentParser(
        description="Enrich Pinecone contract vectors with SAM.gov opp_id"
    )
    parser.add_argument(
        "csv_file",
        help="Path to ContractOpportunitiesFullCSV.csv"
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Pinecone namespace to enrich (default: contracts)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process data but don't upload to Pinecone"
    )
    
    args = parser.parse_args()
    
    # Validate environment
    if not PINECONE_API_KEY:
        print("❌ PINECONE_API_KEY environment variable not set")
        sys.exit(1)
    
    print("=" * 70)
    print("SAM.gov Opportunity ID Enrichment")
    print("=" * 70)
    print(f"📂 CSV Input: {args.csv_file}")
    print(f"📦 Index: {PINECONE_INDEX_NAME}")
    print(f"🏷️  Namespace: {args.namespace}")
    print()
    
    # Validate CSV file exists
    if not Path(args.csv_file).exists():
        print(f"❌ CSV file not found: {args.csv_file}")
        sys.exit(1)
    
    # Initialize Pinecone
    print("🔌 Connecting to Pinecone...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    print()
    
    # Step 1: Build opp_id lookup from CSV
    opp_id_lookup = build_opp_id_lookup(args.csv_file)
    
    if not opp_id_lookup:
        print("❌ No valid opp_id mappings found in CSV")
        sys.exit(1)
    
    # Step 2: Fetch all vectors from Pinecone
    vectors = fetch_all_vectors(index, namespace=args.namespace)
    
    if not vectors:
        print("❌ No vectors found in Pinecone namespace")
        sys.exit(1)
    
    # Step 3: Enrich vectors with opp_id
    enriched_vectors, stats = enrich_vectors_with_opp_id(vectors, opp_id_lookup)
    
    if args.dry_run:
        print("🏃 DRY RUN - Not uploading to Pinecone")
        print("\nSample enriched record:")
        
        # Find a record that was updated
        sample = None
        for v in enriched_vectors:
            if 'opp_id' in v['metadata']:
                sample = v
                break
        
        if sample:
            print(f"  ID: {sample['id']}")
            print(f"  Metadata:")
            for key, value in sample['metadata'].items():
                if key in ['notice_id', 'opp_id', 'title']:
                    print(f"    {key}: {value}")
        
        return
    
    # Step 4: Upsert enriched vectors back to Pinecone
    if stats['updated'] > 0:
        total_uploaded = upsert_enriched_vectors(
            index,
            enriched_vectors,
            namespace=args.namespace
        )
        
        print("=" * 70)
        print("✅ ENRICHMENT COMPLETE")
        print("=" * 70)
        print(f"   Total vectors processed: {stats['total']}")
        print(f"   Vectors enriched with opp_id: {stats['updated']}")
        print(f"   Vectors uploaded: {total_uploaded}")
        print(f"   Match rate: {stats['matched'] / stats['total'] * 100:.1f}%")
    else:
        print("=" * 70)
        print("ℹ️  NO UPDATES NEEDED")
        print("=" * 70)
        print(f"   All {stats['total']} vectors already have opp_id or couldn't be matched")


if __name__ == "__main__":
    main()