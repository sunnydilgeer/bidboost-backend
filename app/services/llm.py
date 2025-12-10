import httpx
import json
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
    
    async def extract_capabilities(self, website_text: str) -> List[dict]:
        """
        Extract 3-5 capabilities from website text.
        Returns structured list ready for database insertion.
        """
        
        # Use OpenAI for better structured output
        if settings.USE_OPENAI_EMBEDDINGS and settings.OPENAI_API_KEY:
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            prompt = f"""Analyze this company website content and extract 3-5 specific capabilities for federal government contracting.

Each capability should be:
- 1-2 sentences describing what they deliver
- Focused on services relevant to federal agencies
- Specific (not generic)

Website content:
{website_text[:4000]}

Return ONLY a JSON array like this:
[
  {{"capability_text": "Cybersecurity consulting with FedRAMP compliance expertise", "category": "IT Services"}},
  {{"capability_text": "Cloud migration for DoD systems", "category": "Defense"}}
]

JSON array:"""

            response = await client.chat.completions.create(
                model="gpt-4o-mini",  # Fast and cheap
                messages=[
                    {"role": "system", "content": "You are a federal contracting expert. Extract capabilities in JSON format only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse JSON (handle markdown fences if present)
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            capabilities = json.loads(result_text)
            
            # Validate structure
            if not isinstance(capabilities, list):
                capabilities = [capabilities]
            
            return capabilities[:5]  # Max 5
        
        else:
            # Fallback to Ollama (less reliable for structured output)
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": f"Extract 3 key business capabilities from this text. Be specific:\n\n{website_text[:2000]}",
                        "stream": False
                    }
                )
                response.raise_for_status()
                text = response.json()["response"]
                
                # Parse as best we can
                return [{"capability_text": text.strip(), "category": "General"}]
    
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