"""
Inspect Pinecone data - verify integrity and structure
Now supports namespace inspection for contracts/companies separation
"""
import sys
from pathlib import Path
import json
import argparse

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings

def inspect_pinecone(namespace: str = "contracts"):
    """Inspect and verify Pinecone data"""
    print("🔍 Connecting to Pinecone...\n")
    store = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
    
    print(f"🏷️  Inspecting namespace: '{namespace}'\n")
    
    # Get index stats
    print("=" * 80)
    print("📊 INDEX STATISTICS")
    print("=" * 80)
    
    stats = store.index.describe_index_stats()
    total_vectors = stats.get('total_vector_count', 0)
    dimension = stats.get('dimension', 0)
    
    print(f"Total Vectors (all namespaces): {total_vectors:,}")
    print(f"Dimensions: {dimension}")
    print(f"Index Fullness: {stats.get('index_fullness', 0):.2%}")
    
    # Show namespace breakdown
    if 'namespaces' in stats and stats['namespaces']:
        print(f"\nNamespace Breakdown:")
        for ns_name, ns_stats in stats['namespaces'].items():
            ns_count = ns_stats.get('vector_count', 0)
            print(f"  📁 '{ns_name}': {ns_count:,} vectors")
    else:
        print(f"\n⚠️  No namespaces found or all in default namespace")
    
    # Check if target namespace exists
    namespace_count = 0
    if namespace and 'namespaces' in stats and namespace in stats['namespaces']:
        namespace_count = stats['namespaces'][namespace].get('vector_count', 0)
        print(f"\n🎯 Target namespace '{namespace}': {namespace_count:,} vectors")
    elif namespace:
        print(f"\n⚠️  Namespace '{namespace}' not found or empty!")
        print("Available namespaces:", list(stats.get('namespaces', {}).keys()))
        return
    
    if namespace_count == 0:
        print(f"\n⚠️  No vectors found in namespace '{namespace}'!")
        return
    
    # Fetch sample vectors from the specified namespace
    print("\n" + "=" * 80)
    print(f"📄 SAMPLE VECTORS FROM '{namespace}' (First 3)")
    print("=" * 80)
    
    # Query for some vectors to get their IDs
    query_vector = [0.0] * dimension  # Dummy vector
    results = store.index.query(
        vector=query_vector,
        top_k=3,
        include_metadata=True,
        namespace=namespace  # ← CRITICAL: Query the right namespace
    )
    
    if not results.get('matches'):
        print(f"\n⚠️  Could not fetch sample vectors from namespace '{namespace}'")
        return
    
    for i, match in enumerate(results['matches'], 1):
        print(f"\n--- Vector {i} ---")
        print(f"ID: {match['id']}")
        print(f"Score: {match.get('score', 'N/A')}")
        
        metadata = match.get('metadata', {})
        print(f"\nMetadata ({len(metadata)} fields):")
        
        # Pretty print metadata with better formatting
        for key, value in sorted(metadata.items()):
            value_str = str(value)
            if len(value_str) > 60:
                value_str = value_str[:60] + "..."
            print(f"  {key:20} : {value_str}")
    
    # Validate required fields
    print("\n" + "=" * 80)
    print("✅ FIELD VALIDATION")
    print("=" * 80)
    
    required_fields = [
        'notice_id', 'title', 'agency', 'naics_code', 'psc_code', 
        'set_aside', 'state', 'response_deadline', 'url'
    ]
    
    # New fields from Contract_Notice_Details.csv
    new_fields = ['opportunity_type', 'status']
    
    sample_metadata = results['matches'][0].get('metadata', {})
    
    print("\nRequired fields check:")
    for field in required_fields:
        exists = field in sample_metadata
        has_value = bool(sample_metadata.get(field))
        status = "✅" if exists else "❌"
        value_status = "✅ Has value" if has_value else "⚠️  Empty/None"
        print(f"  {status} {field:20} - {value_status}")
        if exists and has_value:
            print(f"     Example: {str(sample_metadata[field])[:60]}...")
    
    print("\nNew fields from Contract_Notice_Details.csv:")
    for field in new_fields:
        exists = field in sample_metadata
        has_value = bool(sample_metadata.get(field))
        status = "✅" if exists else "❌"
        value_status = f"Value: {sample_metadata.get(field)}" if has_value else "Empty/None"
        print(f"  {status} {field:20} - {value_status}")
    
    # Check for old format artifacts (shouldn't exist in new migration)
    print("\nOld format check (should NOT exist):")
    old_format_fields = ['NoticeId', 'Title', 'Department', 'NaicsCode', 'Sol#']
    has_old_format = False
    for field in old_format_fields:
        if field in sample_metadata:
            print(f"  ⚠️  Found old field: {field}")
            has_old_format = True
    
    if not has_old_format:
        print(f"  ✅ No old format artifacts detected")
    
    # Check for scoring-critical fields
    print("\n" + "=" * 80)
    print("🎯 SCORING-CRITICAL FIELDS")
    print("=" * 80)
    
    scoring_fields = {
        'naics_code': 'NAICS Code (for capability matching)',
        'psc_code': 'PSC Code (for capability matching)',
        'set_aside': 'Set-Aside Type (for +15% bonus)',
        'state': 'State (for preference matching)',
        'agency': 'Agency (for past performance matching)',
        'opportunity_type': 'Opportunity Type (for filtering)',
        'status': 'Status (for active filtering)'
    }
    
    for field, description in scoring_fields.items():
        value = sample_metadata.get(field)
        if value and str(value).strip():
            print(f"✅ {field:20} - {description}")
            print(f"   Value: {value}")
        else:
            print(f"⚠️  {field:20} - {description}")
            print(f"   WARNING: Empty or missing!")
    
    # Summary
    print("\n" + "=" * 80)
    print("📋 SUMMARY")
    print("=" * 80)
    print(f"✅ {namespace_count:,} vectors in namespace '{namespace}'")
    print(f"✅ {total_vectors:,} total vectors across all namespaces")
    print(f"✅ {dimension} dimensions (OpenAI embeddings)")
    
    missing_fields = [f for f in required_fields if f not in sample_metadata]
    empty_fields = [f for f in required_fields if not sample_metadata.get(f)]
    
    if missing_fields:
        print(f"⚠️  Missing required fields: {', '.join(missing_fields)}")
    
    if empty_fields:
        print(f"⚠️  Empty fields in sample: {', '.join(empty_fields)}")
    
    # Check new fields
    missing_new = [f for f in new_fields if f not in sample_metadata]
    if missing_new:
        print(f"⚠️  Missing new fields: {', '.join(missing_new)}")
        print("   This might indicate old data format - consider re-ingesting")
    else:
        print(f"✅ New Contract_Notice_Details.csv fields present")
    
    if not missing_fields and len(empty_fields) <= 2:  # Description and set_aside can be empty
        print("✅ Data structure looks good!")
        print("✅ Ready for scoring!")
    else:
        print("⚠️  Some data quality issues found")
    
    if has_old_format:
        print("⚠️  OLD FORMAT DETECTED - Re-ingestion recommended!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect Pinecone data quality and structure")
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Namespace to inspect (default: contracts)"
    )
    args = parser.parse_args()
    
    inspect_pinecone(namespace=args.namespace)