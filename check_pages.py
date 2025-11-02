import asyncio
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService

async def check_pages():
    vector_store = VectorStoreService()
    llm = LLMService()
    
    # Search for any content from your uploaded document
    results = await vector_store.search(
        query_text="subcontractor agreement",
        llm_service=llm,
        limit=5
    )
    
    print("\n=== Checking Page Numbers in Vector Store ===\n")
    for i, result in enumerate(results, 1):
        print(f"Result {i}:")
        print(f"  Page: {result.get('page', 'MISSING')}")
        print(f"  Metadata page: {result.get('metadata', {}).get('page', 'MISSING')}")
        print(f"  Content preview: {result['content'][:100]}...")
        print()

asyncio.run(check_pages())
