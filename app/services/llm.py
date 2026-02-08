import httpx
import json
import asyncio
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
        Extract 5-8 specific, concrete service capabilities from website text.
        Focuses on WHAT they deliver across ALL service types.
        
        Returns: List of dicts with structure:
            [{"capability_text": "Service description", "category": "Category name"}, ...]
        """
        
        # Use OpenAI for better structured output
        if settings.USE_OPENAI_EMBEDDINGS and settings.OPENAI_API_KEY:
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            # ✅ INCREASED: Use first 12000 chars instead of 6000
            # ✅ SMARTER: Prioritize content (often where services are described)
            content_window = website_text[:12000]
            
            prompt = f"""Analyze this company website and extract 5-8 SPECIFIC service capabilities.

WHAT TO EXTRACT:
Extract CONCRETE SERVICES they provide. Look for:

✅ Physical services: facility management, operations, maintenance, construction, infrastructure
✅ Technology services: cloud, software, IT systems, applications, platforms  
✅ Energy services: energy management, utilities, HVAC, electrical, mechanical
✅ Consulting: advisory, strategy, transformation, implementation
✅ Professional services: training, support, staffing, project management
✅ Industry-specific: healthcare IT, defense systems, financial tech, government solutions
✅ Named products/platforms: specific software, tools, or systems they deploy

EXAMPLES OF GOOD EXTRACTIONS:

For a facilities company:
- "Facility operations and maintenance services for mission-critical government and commercial buildings"
- "Energy management solutions including HVAC optimization and utility cost reduction"
- "Infrastructure modernization and capital project management"

For a tech company:
- "Cloud migration and modernization services for AWS, Azure, and GCP"
- "Workday implementation and integration with existing enterprise systems"
- "Cybersecurity consulting and FedRAMP authorization support"

For a hybrid company:
- "IT infrastructure management and 24/7 help desk support"
- "Building automation systems and smart facility technology"
- "Digital transformation consulting for operational efficiency"

RULES:
1. Each capability = 1-2 sentences describing a SPECIFIC service offering
2. Be concrete — mention technologies, industries, or outcomes when possible
3. Avoid: mission statements, values, vague descriptions
4. Focus on deliverables, not aspirations

Website content:
{content_window}

Return ONLY valid JSON (no markdown, no backticks, no explanation):
[
  {{"capability_text": "Specific service description here", "category": "Service Type"}},
  {{"capability_text": "Another specific service here", "category": "Service Type"}}
]"""

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": "You extract specific service capabilities from company websites. Focus on WHAT THEY DO (concrete services, products, solutions) across ALL industries — technology, facilities, energy, consulting, construction, professional services, etc. You output ONLY valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Slightly higher for more diverse extraction
                max_tokens=1500
            )
            
            result_text = response.choices[0].message.content.strip()
            print(f"🤖 GPT-4o-mini extraction result:")
            print(f"{'='*70}")
            print(result_text)
            print(f"{'='*70}")

            
            # Clean markdown fences if present
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            try:
                capabilities = json.loads(result_text)
            except json.JSONDecodeError as e:
                print(f"❌ JSON parsing error: {e}")
                print(f"Raw response: {result_text[:500]}")
                # Fallback to generic
                return [{
                    "capability_text": "Professional services and solutions",
                    "category": "General Services"
                }]
            
            # Validate structure
            if not isinstance(capabilities, list):
                capabilities = [capabilities]
            
            # Ensure each item has required fields
            validated_capabilities = []
            for cap in capabilities:
                if isinstance(cap, dict) and "capability_text" in cap:
                    validated_capabilities.append({
                        "capability_text": cap["capability_text"],
                        "category": cap.get("category", "General")
                    })
            
            # Return 5-8 capabilities (or whatever we got)
            if not validated_capabilities:
                return [{
                    "capability_text": "Professional services and solutions",
                    "category": "General Services"
                }]
            
            return validated_capabilities[:8]
        
        else:
            # Fallback to Ollama (less reliable for structured output)
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": f"Extract 3-5 specific service capabilities from this company website. Focus on concrete services they offer:\n\n{website_text[:2000]}",
                        "stream": False
                    }
                )
                response.raise_for_status()
                text = response.json()["response"]
                
                # Parse as best we can - Ollama output is less structured
                lines = [line.strip() for line in text.split('\n') if line.strip() and len(line.strip()) > 20]
                capabilities = []
                for line in lines[:5]:
                    # Remove bullet points and numbering
                    cleaned = line.lstrip('•-*123456789. ')
                    if cleaned:
                        capabilities.append({
                            "capability_text": cleaned,
                            "category": "General"
                        })
                
                return capabilities if capabilities else [{
                    "capability_text": text.strip()[:200],
                    "category": "General"
                }]
    
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


# ============================================================================
# Singleton and Helper Functions
# ============================================================================

# Singleton instance
_llm_service_instance = None

def get_llm_service() -> LLMService:
    """Get singleton LLM service instance"""
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = LLMService()
    return _llm_service_instance


def generate_embeddings_sync(text: str) -> List[float]:
    """Synchronous wrapper for embeddings (for background jobs)"""
    llm_service = get_llm_service()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(llm_service.generate_embeddings(text))
    finally:
        loop.close()