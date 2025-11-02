from qdrant_client import QdrantClient

client = QdrantClient(host="localhost", port=6333)

# Check company_documents collection
try:
    result = client.scroll(
        collection_name="company_documents",
        limit=10,
        with_payload=True
    )
    
    print(f"✓ Found {len(result[0])} document chunks in company_documents collection")
    
    for point in result[0]:
        print(f"\nDocument ID: {point.payload.get('document_id')}")
        print(f"Company ID: {point.payload.get('company_id')}")
        print(f"Filename: {point.payload.get('filename')}")
        print(f"Chunk: {point.payload.get('chunk_text')[:100]}...")
        
except Exception as e:
    print(f"✗ Error checking company_documents: {e}")

# Check contracts collection
try:
    contracts_info = client.get_collection("legal_documents")
    print(f"\n✓ Contracts collection has {contracts_info.points_count} contracts")
except Exception as e:
    print(f"✗ Error checking contracts collection: {e}")