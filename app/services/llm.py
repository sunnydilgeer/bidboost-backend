import httpx
import json
import asyncio
import logging
from typing import List
from app.core.config import settings

logger = logging.getLogger(__name__)

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
        🆕 FIXED: Extract capabilities that are ACTUALLY on the company's website.
        
        BUG FIXES:
        - Removed example-based prompting that caused hallucination
        - Added validation to verify extracted capabilities match scraped text
        - Added debugging logs to track what's being sent to LLM
        - Stricter prompt instructions
        
        Returns: List of dicts with structure:
            [{"capability_text": "Service description", "category": "Category name"}, ...]
        """
        
        # Use OpenAI for better structured output
        if settings.USE_OPENAI_EMBEDDINGS and settings.OPENAI_API_KEY:
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            # Use first 12000 chars (enough to capture multiple pages)
            content_window = website_text[:12000]
            
            # 🆕 DEBUG LOGGING: Show what we're actually sending to the LLM
            logger.info("="*70)
            logger.info("📝 CAPABILITY EXTRACTION - SCRAPED TEXT PREVIEW")
            logger.info("="*70)
            logger.info(f"Total text length: {len(website_text):,} chars")
            logger.info(f"Content window: {len(content_window):,} chars")
            logger.info(f"\nFirst 1000 chars of scraped text:")
            logger.info("-"*70)
            logger.info(content_window[:1000])
            logger.info("-"*70)
            
            # 🆕 KEYWORD DETECTION: Check what domains are present
            text_lower = content_window.lower()
            domain_keywords = {
                'IT/Software': ['software', 'cloud', 'application', 'cybersecurity', 'data', 'api', 'programming'],
                'Construction/Facilities': ['construction', 'facility', 'building', 'maintenance', 'hvac', 'renovation'],
                'Energy': ['energy', 'power', 'utilities', 'solar', 'electrical'],
                'Consulting': ['consulting', 'advisory', 'strategy', 'transformation']
            }
            
            logger.info("\n🔍 DOMAIN KEYWORD DETECTION:")
            for domain, keywords in domain_keywords.items():
                matches = [kw for kw in keywords if kw in text_lower]
                if matches:
                    logger.info(f"  {domain}: {', '.join(matches)}")
            logger.info("="*70)
            
            # 🆕 STRICTER PROMPT: No examples, just instructions
            prompt = f"""Extract 5-8 service capabilities from this company's website.

CRITICAL RULES:
✅ Extract ONLY capabilities that are explicitly written on their website
✅ Use the company's actual language and terminology from the text below
✅ Be specific - include technologies, tools, frameworks, or industries they mention
✅ Each capability should be 1-2 sentences describing what they DO (not who they are)

❌ DO NOT infer or add capabilities not mentioned in the text
❌ DO NOT use generic federal contracting language unless it's in their text
❌ DO NOT hallucinate services based on what companies "typically" offer
❌ DO NOT add capabilities from other companies or examples

VALIDATION STEP (before returning):
- Re-read the website text below
- Verify each extracted capability uses words/phrases from the text
- If a capability doesn't match the text, remove it

WEBSITE TEXT:
{content_window}

Return ONLY valid JSON (no markdown, no backticks):
[
  {{"capability_text": "Specific service they mention (use their words)", "category": "Service Type"}},
  {{"capability_text": "Another service from their website", "category": "Service Type"}}
]"""

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a precise capability extractor. You ONLY extract services that are explicitly stated on the company's website. You never infer, hallucinate, or add capabilities not mentioned in the provided text. You output valid JSON only."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # 🆕 LOWER: Reduce creativity/hallucination
                max_tokens=1500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            logger.info("\n🤖 GPT-4o-mini EXTRACTION RESULT:")
            logger.info("="*70)
            logger.info(result_text)
            logger.info("="*70)
            
            # Clean markdown fences if present
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            try:
                capabilities = json.loads(result_text)
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON parsing error: {e}")
                logger.error(f"Raw response (first 500 chars): {result_text[:500]}")
                return [{
                    "capability_text": "Professional services and solutions",
                    "category": "General Services"
                }]
            
            # Validate structure
            if not isinstance(capabilities, list):
                capabilities = [capabilities]
            
            # 🆕 POST-EXTRACTION VALIDATION: Verify capabilities match scraped text
            validated_capabilities = []
            text_lower_for_validation = content_window.lower()
            
            logger.info("\n✅ VALIDATING EXTRACTED CAPABILITIES:")
            logger.info("="*70)
            
            for idx, cap in enumerate(capabilities):
                if not isinstance(cap, dict) or "capability_text" not in cap:
                    logger.warning(f"  [{idx+1}] ⚠️ Invalid structure, skipping")
                    continue
                
                cap_text = cap["capability_text"]
                cap_lower = cap_text.lower()
                
                # Extract significant words (ignore common words)
                stop_words = {'and', 'the', 'for', 'with', 'that', 'this', 'from', 'services', 
                             'solutions', 'including', 'provide', 'provide', 'support', 'our', 
                             'we', 'are', 'is', 'to', 'of', 'in', 'on'}
                
                significant_words = [
                    word for word in cap_lower.split() 
                    if len(word) > 4 and word not in stop_words
                ][:8]  # Check first 8 significant words
                
                # Count how many significant words appear in scraped text
                matches = sum(1 for word in significant_words if word in text_lower_for_validation)
                match_percentage = (matches / len(significant_words) * 100) if significant_words else 0
                
                # 🆕 THRESHOLD: At least 40% of significant words must match
                if match_percentage >= 40:
                    validated_capabilities.append({
                        "capability_text": cap_text,
                        "category": cap.get("category", "General")
                    })
                    logger.info(f"  [{idx+1}] ✅ VALID ({match_percentage:.0f}% match)")
                    logger.info(f"       \"{cap_text[:80]}...\"")
                    logger.info(f"       Matched words: {[w for w in significant_words if w in text_lower_for_validation]}")
                else:
                    logger.warning(f"  [{idx+1}] ❌ REJECTED ({match_percentage:.0f}% match - likely hallucination)")
                    logger.warning(f"       \"{cap_text[:80]}...\"")
                    logger.warning(f"       Only {matches}/{len(significant_words)} significant words found in scraped text")
            
            logger.info("="*70)
            logger.info(f"📊 VALIDATION SUMMARY: {len(validated_capabilities)}/{len(capabilities)} capabilities passed validation")
            logger.info("="*70 + "\n")
            
            # If validation was too aggressive and rejected everything, relax threshold
            if not validated_capabilities and len(capabilities) > 0:
                logger.warning("⚠️ Validation rejected all capabilities, using relaxed threshold (25%)")
                for cap in capabilities:
                    if isinstance(cap, dict) and "capability_text" in cap:
                        cap_text = cap["capability_text"]
                        cap_lower = cap_text.lower()
                        
                        significant_words = [
                            word for word in cap_lower.split() 
                            if len(word) > 4 and word not in stop_words
                        ][:8]
                        
                        matches = sum(1 for word in significant_words if word in text_lower_for_validation)
                        match_percentage = (matches / len(significant_words) * 100) if significant_words else 0
                        
                        if match_percentage >= 25:  # Relaxed threshold
                            validated_capabilities.append({
                                "capability_text": cap_text,
                                "category": cap.get("category", "General")
                            })
            
            # Return validated capabilities (5-8 max)
            if not validated_capabilities:
                logger.error("❌ No valid capabilities extracted, using fallback")
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