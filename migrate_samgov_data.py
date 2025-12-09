"""
SAM.gov Data Migration Script
Manages the transition from ContractOpportunitiesFullCSV.csv to Contract_Notice_Details.csv

Usage:
    python migrate_samgov_data.py --backup    # Backup current state
    python migrate_samgov_data.py --migrate Contract_Notice_Details.csv
    python migrate_samgov_data.py --verify    # Verify migration
"""

import os
import sys
import json
import argparse
from datetime import datetime

from dotenv import load_dotenv
from pinecone import Pinecone

# Load environment variables from .env file
load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")


def backup_index_stats(index, output_dir: str = "."):
    """Save current index statistics before migration."""
    stats = index.describe_index_stats()
    
    backup_data = {
        "timestamp": datetime.now().isoformat(),
        "total_vectors": stats.total_vector_count,
        "dimensions": stats.dimension,
        "namespaces": {k: v.to_dict() for k, v in stats.namespaces.items()},
        "index_fullness": stats.index_fullness,
    }
    
    # Sample some vectors for reference
    print("📸 Sampling vectors for backup reference...")
    try:
        # Query with a zero vector to get random samples
        results = index.query(
            vector=[0.0] * stats.dimension,
            top_k=10,
            include_metadata=True,
            namespace=""
        )
        backup_data["sample_vectors"] = [
            {"id": m.id, "metadata": m.metadata}
            for m in results.matches
        ]
    except Exception as e:
        print(f"   Warning: Could not sample vectors: {e}")
        backup_data["sample_vectors"] = []
    
    filename = f"pinecone_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, 'w') as f:
        json.dump(backup_data, f, indent=2, default=str)
    
    print(f"✅ Backup saved to: {filepath}")
    print(f"   Vectors: {backup_data['total_vectors']}")
    print(f"   Dimensions: {backup_data['dimensions']}")
    
    return filepath


def verify_migration(index, namespace: str = "contracts", expected_min: int = 10000):
    """Verify the migration was successful."""
    print("=" * 70)
    print("🔍 MIGRATION VERIFICATION")
    print("=" * 70)
    
    stats = index.describe_index_stats()
    
    print(f"\n📊 Index Statistics:")
    print(f"   Total vectors (all namespaces): {stats.total_vector_count}")
    print(f"   Dimensions: {stats.dimension}")
    print(f"   Index fullness: {stats.index_fullness:.2%}")
    
    # Show namespace-specific count
    if namespace in stats.namespaces:
        namespace_count = stats.namespaces[namespace].vector_count
        print(f"   Namespace '{namespace}': {namespace_count} vectors")
    else:
        print(f"   ⚠️  Namespace '{namespace}' not found or empty")
        namespace_count = 0
    
    # Sample and check metadata fields
    print(f"\n📋 Checking metadata structure in namespace '{namespace}'...")
    try:
        results = index.query(
            vector=[0.0] * stats.dimension,
            top_k=5,
            include_metadata=True,
            namespace=namespace
        )
        
        required_fields = [
            "notice_id", "title", "agency", "naics_code", 
            "psc_code", "set_aside", "state", "response_deadline", "url"
        ]
        
        new_fields = ["opportunity_type", "status"]  # New fields from migration
        
        sample = results.matches[0] if results.matches else None
        
        if sample and sample.metadata:
            print(f"\n   Sample vector ID: {sample.id}")
            
            # Check required fields
            for field in required_fields:
                value = sample.metadata.get(field, "MISSING")
                status = "✅" if value != "MISSING" else "❌"
                display_val = str(value)[:50] + "..." if len(str(value)) > 50 else value
                print(f"   {status} {field}: {display_val}")
            
            # Check new fields (should exist after migration)
            print(f"\n   New fields from Contract_Notice_Details.csv:")
            for field in new_fields:
                value = sample.metadata.get(field, "MISSING")
                status = "✅" if value and value != "MISSING" else "⚠️"
                print(f"   {status} {field}: {value}")
            
            # Check for old fields that shouldn't exist in new format
            old_only_fields = ["Sol#", "CGAC", "FPDS Code"]  # Fields only in old CSV
            has_old_format = any(f in sample.metadata for f in old_only_fields)
            
            if has_old_format:
                print(f"\n   ⚠️  WARNING: Found old format fields - migration may be incomplete")
            else:
                print(f"\n   ✅ No old format artifacts detected")
        
    except Exception as e:
        print(f"   ❌ Error sampling vectors: {e}")
    
    # Summary
    print(f"\n" + "=" * 70)
    if namespace_count >= expected_min:
        print(f"✅ VERIFICATION PASSED")
        print(f"   Namespace '{namespace}': {namespace_count} vectors (expected ≥{expected_min})")
    else:
        print(f"⚠️  VERIFICATION WARNING")
        print(f"   Namespace '{namespace}': Only {namespace_count} vectors (expected ≥{expected_min})")
    print("=" * 70)
    
    return namespace_count >= expected_min


def show_migration_plan():
    """Display the migration plan."""
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║                     SAM.GOV DATA MIGRATION PLAN                       ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║  FROM: ContractOpportunitiesFullCSV.csv (11,896 vectors)             ║
║    TO: Contract_Notice_Details.csv (~20,726 biddable)                ║
║                                                                       ║
║  🏷️  USING NAMESPACES FOR ORGANIZATION:                              ║
║     - contracts: SAM.gov contract opportunities                      ║
║     - companies: Company capability profiles                         ║
║                                                                       ║
║  STEPS:                                                               ║
║                                                                       ║
║  1. BACKUP (recommended)                                              ║
║     python migrate_samgov_data.py --backup                           ║
║                                                                       ║
║  2. MIGRATE (clears contracts namespace + ingests new)               ║
║     python ingest_contract_notice_details.py \\                       ║
║         Contract_Notice_Details.csv \\                                ║
║         --clear-existing --namespace contracts                       ║
║                                                                       ║
║  3. VERIFY                                                            ║
║     python migrate_samgov_data.py --verify --namespace contracts    ║
║                                                                       ║
║  FIELD MAPPING:                                                       ║
║    NoticeId          → Notice ID                                     ║
║    Title             → Opportunity Title                             ║
║    Department        → Sub Tier Name                                 ║
║    NaicsCode         → NAICS                                         ║
║    ClassificationCode → PSC                                          ║
║    SetASide          → Current Set Aside                             ║
║    ResponseDeadLine  → Current Response Date                         ║
║    PopState          → Place of Performance - State                  ║
║                                                                       ║
║  NEW METADATA FIELDS (post-migration):                               ║
║    - opportunity_type (for filtering)                                ║
║    - status (active/inactive tracking)                               ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝
""")


def main():
    parser = argparse.ArgumentParser(
        description="SAM.gov Data Migration Helper"
    )
    parser.add_argument("--backup", action="store_true", help="Backup current index state")
    parser.add_argument("--verify", action="store_true", help="Verify migration success")
    parser.add_argument("--plan", action="store_true", help="Show migration plan")
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Pinecone namespace to verify (default: contracts)"
    )
    parser.add_argument(
        "--expected-min", 
        type=int, 
        default=15000,
        help="Minimum expected vectors after migration"
    )
    
    args = parser.parse_args()
    
    if args.plan:
        show_migration_plan()
        return
    
    if not PINECONE_API_KEY:
        print("❌ PINECONE_API_KEY environment variable not set")
        sys.exit(1)
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    
    if args.backup:
        backup_index_stats(index)
    elif args.verify:
        verify_migration(index, namespace=args.namespace, expected_min=args.expected_min)
    else:
        show_migration_plan()


if __name__ == "__main__":
    main()