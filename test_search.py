import asyncio
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService

async def test_search():
    vector_store = VectorStoreService()
    llm_service = LLMService()
    
    queries = [
        "cybersecurity cloud infrastructure AWS",
        "software development agile",
        "construction building maintenance"
    ]
    
    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)
        
        results = await vector_store.search_contracts(
            query_text=query,
            llm_service=llm_service,
            limit=3
        )
        
        for i, result in enumerate(results, 1):
            # Handle dict response
            title = result.get('title', 'No title') if isinstance(result, dict) else result.title
            score = result.get('score', 0) if isinstance(result, dict) else result.score
            buyer = result.get('buyer_name', 'Unknown') if isinstance(result, dict) else result.buyer_name
            metadata = result.get('metadata', {}) if isinstance(result, dict) else result.metadata
            closing = result.get('closing_date') if isinstance(result, dict) else result.closing_date
            
            print(f"\n{i}. {title[:80]}...")
            print(f"   Score: {score:.3f}")
            print(f"   Buyer: {buyer}")
            print(f"   Source: {metadata.get('source', 'Unknown')}")
            if closing:
                print(f"   Closes: {closing}")

asyncio.run(test_search())
