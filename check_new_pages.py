import asyncio
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService

async def check_pages():
    vector_store = VectorStoreService()
    llm = LLMService()
    
    results = await vector_store.search(
        query_text="subcontractor agreement",
        llm_service=llm,
        limit=10
    )
    
    print("\n=== Checking Page Numbers After Fix ===\n")
    for i, result in enumerate(results, 1):
        page = result.get('page', 'MISSING')
        content_preview = result['content'][:80].replace('\n', ' ')
        print(f"{i}. Page {page}: {content_preview}...")
    
    # Check for variety in page numbers
    pages = [r.get('page', 1) for r in results]
    print(f"\nUnique pages found: {set(pages)}")
    print(f"All showing page 1? {'YES - PROBLEM!' if set(pages) == {1} else 'NO - Looking good!'}")

asyncio.run(check_pages())
