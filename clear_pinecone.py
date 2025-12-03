"""
Clear all vectors from Pinecone contracts collection
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings

def clear_pinecone():
    """Delete all vectors from Pinecone"""
    print("🗑️  Connecting to Pinecone...")
    store = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
    
    # Get current count
    try:
        stats = store.index.describe_index_stats()
        total_vectors = stats.get('total_vector_count', 0)
        print(f"📊 Current vector count: {total_vectors:,}")
        
        if total_vectors == 0:
            print("✅ Collection is already empty!")
            return
        
        # Confirm deletion
        response = input(f"\n⚠️  Delete all {total_vectors:,} vectors? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Cancelled")
            return
        
        # Delete all vectors
        print("\n🗑️  Deleting all vectors...")
        store.index.delete(delete_all=True)
        
        print("✅ All vectors deleted!")
        
        # Verify
        stats = store.index.describe_index_stats()
        remaining = stats.get('total_vector_count', 0)
        print(f"📊 Remaining vectors: {remaining:,}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    clear_pinecone()