import httpx
from typing import List, Dict, Any
from app.core.config import settings

class LLMService:
    def __init__(self):
        self.model = settings.OLLAMA_MODEL  # For chat/generation
        self.embedding_model = settings.OLLAMA_EMBEDDING_MODEL  # For embeddings
        self.base_url = "http://localhost:11434"
    
    async def generate_embeddings(self, text: str) -> List[float]:
        """Generate embedding using direct HTTP call to Ollama API"""
        request_data = {
            "model": "nomic-embed-text",
            "prompt": text
        }
        
        print(f"DEBUG: Sending embedding request: {request_data}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json=request_data
            )
            print(f"DEBUG: Response status: {response.status_code}")
            print(f"DEBUG: Response text: {response.text[:200]}...")
            
            response.raise_for_status()
            return response.json()["embedding"]
    
    async def generate_response(
        self, 
        question: str,
        context: str,
        system_prompt: str = None
    ) -> str:
        """Generate a response using RAG context"""
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