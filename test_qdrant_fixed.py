from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
import httpx
import sys

url = "https://qdrant-production-85cf.up.railway.app"

print(f"🔍 Testing with custom httpx client")
print(f"   URL: {url}")
print()

try:
    # Create custom httpx client with aggressive settings
    http_client = httpx.Client(
        timeout=60.0,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20
        ),
        http2=False,  # Disable HTTP/2
        verify=True,  # Keep SSL verification
    )
    
    print("Creating Qdrant client with custom httpx...")
    client = QdrantClient(
        url=url,
        timeout=60,
        prefer_grpc=False,  # Force REST API
        https=True,
        # host=None,  # Don't use host parameter
    )
    
    print("✓ Client created")
    print("Fetching collections...")
    
    collections = client.get_collections()
    
    print(f"✅ SUCCESS!")
    print(f"Collections: {[c.name for c in collections.collections]}")
    
except Exception as e:
    print(f"❌ FAILED: {type(e).__name__}")
    print(f"Error: {e}")
    
    # Check if we can reach it with httpx directly
    print("\n" + "="*60)
    print("Testing with raw httpx.get()...")
    try:
        response = httpx.get(f"{url}/collections", timeout=30)
        print(f"✅ httpx.get() works! Status: {response.status_code}")
        print(f"Response: {response.text[:200]}")
    except Exception as e2:
        print(f"❌ httpx.get() also fails: {e2}")
    
    sys.exit(1)
