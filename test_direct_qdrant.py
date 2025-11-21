from qdrant_client import QdrantClient
import sys

url = "https://qdrant-production-85cf.up.railway.app"

print(f"🔍 Testing direct connection to: {url}")
print(f"   Timeout: 30 seconds")
print()

try:
    print("Connecting...")
    client = QdrantClient(url=url, timeout=30)
    
    print("✓ Client created")
    
    print("Fetching collections...")
    collections = client.get_collections()
    
    print(f"✅ SUCCESS! Connected to Qdrant")
    print(f"Collections: {[c.name for c in collections.collections]}")
    sys.exit(0)
    
except Exception as e:
    print(f"❌ FAILED: {type(e).__name__}")
    print(f"Error: {e}")
    
    import traceback
    print("\nFull traceback:")
    traceback.print_exc()
    sys.exit(1)
