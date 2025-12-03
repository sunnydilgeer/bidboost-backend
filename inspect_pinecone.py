"""
Inspect Pinecone data - verify integrity and structure
"""
import sys
from pathlib import Path
import json

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings

def inspect_pinecone():
    """Inspect and verify Pinecone data"""
    print("🔍 Connecting to Pinecone...\n")
    store = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
    
    # Get index stats
    print("=" * 80)
    print("📊 INDEX STATISTICS")
    print("=" * 80)
    
    stats = store.index.describe_index_stats()
    total_vectors = stats.get('total_vector_count', 0)
    dimension = stats.get('dimension', 0)
    
    print(f"Total Vectors: {total_vectors:,}")
    print(f"Dimensions: {dimension}")
    print(f"Index Fullness: {stats.get('index_fullness', 0):.2%}")
    
    if 'namespaces' in stats:
        print(f"\nNamespaces: {stats['namespaces']}")
    
    if total_vectors == 0:
        print("\n⚠️  No vectors found in index!")
        return
    
    # Fetch sample vectors
    print("\n" + "=" * 80)
    print("📄 SAMPLE VECTORS (First 3)")
    print("=" * 80)
    
    # Query for some vectors to get their IDs
    query_vector = [0.0] * dimension  # Dummy vector
    results = store.index.query(
        vector=query_vector,
        top_k=3,
        include_metadata=True
    )
    
    if not results.get('matches'):
        print("\n⚠️  Could not fetch sample vectors")
        return
    
    for i, match in enumerate(results['matches'], 1):
        print(f"\n--- Vector {i} ---")
        print(f"ID: {match['id']}")
        print(f"Score: {match.get('score', 'N/A')}")
        
        metadata = match.get('metadata', {})
        print(f"\nMetadata ({len(metadata)} fields):")
        print(json.dumps(metadata, indent=2))
    
    # Validate required fields
    print("\n" + "=" * 80)
    print("✅ FIELD VALIDATION")
    print("=" * 80)
    
    required_fields = [
        'notice_id', 'title', 'agency', 'naics_code', 'psc_code', 
        'set_aside', 'state', 'response_deadline', 'url'
    ]
    
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
    
    # Check for scoring-critical fields
    print("\n" + "=" * 80)
    print("🎯 SCORING-CRITICAL FIELDS")
    print("=" * 80)
    
    scoring_fields = {
    'naics_code': 'NAICS Code (for capability matching)',
    'psc_code': 'PSC Code (for capability matching)',
    'set_aside': 'Set-Aside Type (for +15% bonus)',
    'state': 'State (for preference matching)',
    'agency': 'Agency (for past performance matching)'
    }
    
    for field, description in scoring_fields.items():
        value = sample_metadata.get(field)
        if value and str(value).strip():
            print(f"✅ {field:15} - {description}")
            print(f"   Value: {value}")
        else:
            print(f"⚠️  {field:15} - {description}")
            print(f"   WARNING: Empty or missing!")
    
    # Summary
    print("\n" + "=" * 80)
    print("📋 SUMMARY")
    print("=" * 80)
    print(f"✅ {total_vectors:,} vectors stored")
    print(f"✅ {dimension} dimensions (OpenAI embeddings)")
    
    missing_fields = [f for f in required_fields if f not in sample_metadata]
    empty_fields = [f for f in required_fields if not sample_metadata.get(f)]
    
    if missing_fields:
        print(f"⚠️  Missing fields: {', '.join(missing_fields)}")
    
    if empty_fields:
        print(f"⚠️  Empty fields in sample: {', '.join(empty_fields)}")
    
    if not missing_fields and len(empty_fields) <= 2:  # Description and set_aside can be empty
        print("✅ Data structure looks good!")
        print("✅ Ready for scoring!")
    else:
        print("⚠️  Some data quality issues found")

if __name__ == "__main__":
    inspect_pinecone()