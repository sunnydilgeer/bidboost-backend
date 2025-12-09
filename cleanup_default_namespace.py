"""
Clean up test vectors from __default__ namespace
"""
import os
from dotenv import load_dotenv
from pinecone import Pinecone

# Load environment variables
load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")

def cleanup_default_namespace():
    """Remove test vectors from __default__ namespace"""
    print("🧹 Cleaning up test vectors from __default__ namespace...\n")
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    
    # Get current stats
    stats = index.describe_index_stats()
    
    if '__default__' in stats.get('namespaces', {}):
        default_count = stats['namespaces']['__default__'].get('vector_count', 0)
        print(f"Found {default_count} vectors in __default__ namespace")
        
        if default_count > 0:
            # Delete all vectors in __default__ namespace
            index.delete(delete_all=True, namespace='__default__')
            print(f"✅ Deleted {default_count} test vectors from __default__ namespace")
        else:
            print("✅ __default__ namespace is already empty")
    else:
        print("✅ No __default__ namespace found (already clean)")
    
    # Show final stats
    print("\n" + "=" * 70)
    print("📊 FINAL INDEX STATE")
    print("=" * 70)
    
    stats = index.describe_index_stats()
    print(f"Total vectors: {stats.get('total_vector_count', 0):,}")
    
    if 'namespaces' in stats:
        print("\nNamespace breakdown:")
        for ns_name, ns_stats in stats['namespaces'].items():
            count = ns_stats.get('vector_count', 0)
            print(f"  📁 '{ns_name}': {count:,} vectors")
    
    print("\n✅ Cleanup complete!")

if __name__ == "__main__":
    cleanup_default_namespace()