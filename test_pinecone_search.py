import asyncio
from app.services.pinecone_store import PineconeStoreService
from app.services.llm import LLMService
from app.core.config import settings

async def test_search():
    # Initialize
    pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
    llm = LLMService()
    
    # Search query
    query = "cybersecurity services"
    print(f"🔍 Searching for: '{query}'\n")
    
    # Generate query embedding
    query_vector = await llm.generate_embeddings(query)
    
    # Search
    results = pinecone.search_contracts(query_vector, limit=3, min_score=0.0)
    
    # Display results
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['title']}")
        print(f"   Agency: {result['agency']}")
        print(f"   Score: {result['score']:.3f}")
        print()

if __name__ == "__main__":
    asyncio.run(test_search())