import httpx
from typing import List
from app.core.config import settings

class LLMService:
    def __init__(self):
        self.model = settings.OLLAMA_MODEL
        self.embedding_model = settings.OLLAMA_EMBEDDING_MODEL
        self.base_url = settings.OLLAMA_HOST
    
    async def generate_embeddings(self, text: str) -> List[float]:
        """Generate embedding - OpenAI in production, Ollama in development"""
        
        if settings.USE_OPENAI_EMBEDDINGS:
            # Use OpenAI for production
            from openai import AsyncOpenAI
            
            if not settings.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not set in environment variables")
            
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
                dimensions=768  # Match Nomic's 768 dimensions for Qdrant compatibility
            )
            
            return response.data[0].embedding
        
        else:
            # Use Ollama for local development
            request_data = {
                "model": self.embedding_model,
                "prompt": text
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json=request_data
                )
                response.raise_for_status()
                return response.json()["embedding"]
    
    async def generate_response(
        self, 
        question: str,
        context: str,
        system_prompt: str = None
    ) -> str:
        """Generate a response using RAG context (uses Ollama)"""
        if system_prompt is None:
            system_prompt = """You are a legal AI assistant for UK law firms with access to the firm's internal document library.

CRITICAL INSTRUCTIONS:
- Answer questions directly using the provided document context
- These are internal company documents - you have permission to discuss their contents
- Always cite specific document names and page numbers in your answers
- Quote relevant clauses or sections when helpful
- If information is not in the provided context, say "I cannot find that information in the uploaded documents"
- Be precise, thorough, and use professional legal language

When citing, use format: [Document Name, Page X]"""
        
        prompt = f"""Context from legal documents:
{context}

Question: {question}

Answer:"""
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system_prompt,
                    "stream": False
                }
            )
            response.raise_for_status()
            return response.json()["response"]