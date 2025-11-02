from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

def create_collection():
    client = QdrantClient(
        host="localhost",  # Your QDRANT_HOST from config
        port=6333          # Your QDRANT_PORT from config
    )
    
    try:
        client.get_collection("company_documents")
        print("✓ Collection 'company_documents' already exists")
    except:
        client.create_collection(
            collection_name="company_documents",
            vectors_config=VectorParams(size=768, distance=Distance.COSINE)
        )
        print("✓ Created collection 'company_documents'")

if __name__ == "__main__":
    create_collection()