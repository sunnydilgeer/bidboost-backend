from app.services.vector_store import VectorStoreService

v = VectorStoreService()

# Get one point to inspect its structure
response = v.client.scroll(
    collection_name="contract_opportunities",
    limit=1,
    with_payload=True
)

if response[0]:
    point = response[0][0]
    print("Point ID:", point.id)
    print("\nPayload keys:", list(point.payload.keys()))
    print("\nFull payload:")
    for key, value in point.payload.items():
        print(f"  {key}: {str(value)[:100]}...")
