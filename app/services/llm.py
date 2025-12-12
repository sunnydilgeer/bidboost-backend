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
        Focuses on WHAT they deliver, not mission statements or generic descriptions.
        
        Returns: List of dicts with structure:
            [{"capability_text": "Service description", "category": "Category name"}, ...]
        """
        
        # Use OpenAI for better structured output
        if settings.USE_OPENAI_EMBEDDINGS and settings.OPENAI_API_KEY:
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            prompt = f"""Analyze this company website content and extract 5-8 SPECIFIC service capabilities for federal government contracting.

CRITICAL EXTRACTION RULES:
1. Extract CONCRETE SERVICES AND OFFERINGS, not mission statements or generic descriptions
2. Focus on what appears in:
   - Services pages and menus
   - Solutions sections
   - Products listings
   - Technology platforms mentioned
   - Industry expertise areas
3. Look for:
   - Specific technology services (e.g., "Cloud migration for AWS/Azure/GCP")
   - Named products or platforms (e.g., "Workday implementation services")
   - Industry specializations (e.g., "Healthcare data analytics with HIPAA compliance")
   - Technical capabilities (e.g., "DevOps automation and CI/CD pipelines")
   - Consulting services (e.g., "Digital transformation advisory for financial services")
4. Each capability should be 1-2 sentences describing WHAT they deliver, not WHY
5. AVOID:
   - Mission statements ("We're on a mission to...")
   - Generic values ("True partners change the world...")
   - Calls to action ("Explore our services...")
   - Vague descriptions without specifics

Website content:
{website_text[:6000]}

Return ONLY a valid JSON array with NO additional text, markdown, or explanation:
[
  {{"capability_text": "Cloud migration and modernization services for AWS, Azure, and GCP with containerization and microservices architecture", "category": "Cloud Services"}},
  {{"capability_text": "Workday implementation and deployment including integration with existing enterprise systems", "category": "Enterprise Software"}},
  {{"capability_text": "Data analytics and AI/ML solutions for healthcare sector with HIPAA compliance expertise", "category": "Data & AI"}},
  {{"capability_text": "Cybersecurity consulting and FedRAMP authorization support for federal agencies", "category": "Cybersecurity"}},
  {{"capability_text": "Digital transformation advisory services for payment systems and fintech platforms", "category": "Financial Services"}},
  {{"capability_text": "User-centered design and UX services for government digital services", "category": "Design"}},
  {{"capability_text": "Managed IT services and application support for enterprise applications", "category": "IT Services"}}
]"""

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are an expert at analyzing company websites and extracting specific, concrete service capabilities. Your job is to identify WHAT THEY DO (services, products, platforms) NOT WHY they do it (mission, values). Focus on technical services, named products, industry expertise, and consulting offerings. Return ONLY valid JSON with no markdown formatting."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,  # Lower for more focused, consistent extraction
                max_tokens=1200
            )
            
            result_text = response.choices[0].message.content.strip()
            print(f"🤖 GPT-4o-mini raw response:")
            print(f"{'='*70}")
            print(result_text)
            print(f"{'='*70}")

            
            # Handle various JSON formatting issues
            # Remove markdown code fences if present
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            try:
                capabilities = json.loads(result_text)
            except json.JSONDecodeError as e:
                # Log error and return fallback
                print(f"❌ JSON parsing error: {e}")
                print(f"Raw response: {result_text[:200]}")
                return [{
                    "capability_text": "Digital services and technology consulting",
                    "category": "IT Services"
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
            
            # Return 5-8 capabilities
            return validated_capabilities[:8] if validated_capabilities else [{
                "capability_text": "Digital services and technology consulting",
                "category": "IT Services"
            }]
        
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
# Singleton and Helper Functions (ADD THESE AT THE END)
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