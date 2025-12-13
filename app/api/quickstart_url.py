"""
Quick-start URL endpoint for onboarding via company website

Scrapes website → extracts capabilities with LLM → matches contracts

OPUS PURE CAPABILITY APPROACH:
- Uses raw Pinecone semantic similarity scores
- No boosts, no enhancements
- Same scoring logic as dashboard
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from typing import List
import logging
import uuid

from app.services.web_scraper import WebScraperService
from app.services.llm import LLMService
from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings
from app.services.code_lookup import get_code_lookup_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quickstart", tags=["Quick Start"])

class QuickStartURLRequest(BaseModel):
    """Request body for URL-based quick start"""
    company_url: str = Field(..., description="Company website URL")
    
    @validator('company_url')
    def validate_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            v = f'https://{v}'
        return v

class QuickStartURLResponse(BaseModel):
    """Response from URL-based quick start"""
    success: bool
    company_name: str
    capabilities_text: str
    capabilities: List[str]
    matches: List[dict]
    avg_score: float
    pages_scraped: int
    session_id: str

@router.post("/url", response_model=QuickStartURLResponse)
async def quick_start_from_url(request: QuickStartURLRequest):
    """
    Extract capabilities from company URL and find matching contracts.
    
    OPUS PURE CAPABILITY APPROACH:
    - Scrapes website
    - Extracts capabilities with LLM
    - Uses pure Pinecone semantic similarity (no boosts)
    - Same scoring as dashboard
    
    Returns:
        - Extracted capabilities
        - Top 20 matching contracts
        - Pure semantic similarity scores (0-100%)
    """
    
    session_id = str(uuid.uuid4())
    
    logger.info(f"🚀 Quick-start session {session_id[:8]}: Processing URL {request.company_url}")
    
    try:
        # ============================================================
        # STEP 1: Scrape website
        # ============================================================
        logger.info(f"🕷️ STEP 1: Scraping website {request.company_url}")
        
        scraper = WebScraperService()
        scrape_result = await scraper.scrape_company_website(request.company_url)
        
        if not scrape_result["success"]:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to scrape website: {scrape_result.get('error', 'Unknown error')}"
            )
        
        company_name = scrape_result["company_name"]
        capabilities_text = scrape_result["capabilities_text"]
        pages_scraped = scrape_result["pages_scraped"]
        
        logger.info(f"✅ Scraped {pages_scraped} pages, extracted {len(capabilities_text)} chars")
        
        # ============================================================
        # STEP 2: Extract capabilities with LLM
        # ============================================================
        logger.info(f"🤖 STEP 2: Extracting capabilities with LLM")
        
        llm = LLMService()
        capabilities = await llm.extract_capabilities(capabilities_text)
        
        if not capabilities:
            raise HTTPException(
                status_code=400,
                detail="Could not extract capabilities from website content"
            )
        
        logger.info(f"✅ Extracted {len(capabilities)} capabilities")
        
        # ============================================================
        # STEP 3: Generate embedding
        # ============================================================
        logger.info(f"🧬 STEP 3: Generating capability embedding")
        
        # Combine capabilities into single text for embedding
        if capabilities and isinstance(capabilities[0], dict):
            capability_texts = [cap.get("text", cap.get("capability_text", "")) for cap in capabilities[:5]]
        else:
            capability_texts = capabilities[:5]

        combined_capabilities = " ".join(capability_texts)  # Use top 5        
        query_vector = await llm.generate_embeddings(combined_capabilities)
        
        logger.info(f"✅ Generated {len(query_vector)}-dimensional embedding")
        
        # ============================================================
        # STEP 4: Search Pinecone for matching contracts
        # ============================================================
        logger.info(f"🔍 STEP 4: Searching Pinecone for matching contracts")
        
        pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        code_service = get_code_lookup_service()
        
        results = pinecone.search_contracts(
            query_vector=query_vector,
            limit=20,  # Top 20 matches
            min_score=0.40,  # Only show 40%+ matches
            namespace="contracts"
        )
        
        if not results:
            logger.warning(f"No matching contracts found")
            return QuickStartURLResponse(
                success=True,
                company_name=company_name,
                capabilities_text=capabilities_text,
                capabilities=capabilities,
                matches=[],
                avg_score=0,
                pages_scraped=pages_scraped,
                session_id=session_id
            )
        
        logger.info(f"✅ Found {len(results)} matching contracts")
        
        # ============================================================
        # STEP 5: Sort by pure semantic similarity
        # ============================================================
        logger.info("📊 STEP 5: Sorting matches by capability similarity...")
        
        # ✅ OPUS APPROACH: Use raw Pinecone scores (pure semantic similarity)
        # Same logic as dashboard - no boosts, no enhancements
        matches = []
        
        for result in results:
            # Enrich with code names
            enriched_result = code_service.enrich_contract(result)
            
            matches.append({
                "notice_id": enriched_result.get("notice_id", ""),
                "title": enriched_result.get("title", ""),
                "buyer_name": enriched_result.get("agency", ""),
                "description": enriched_result.get("description", ""),
                "contract_value": enriched_result.get("contract_value"),
                "region": enriched_result.get("state"),
                "closing_date": enriched_result.get("response_deadline"),
                "naics_code": enriched_result.get("naics_code"),
                "naics_name": enriched_result.get("naics_name"),
                "psc_code": enriched_result.get("psc_code"),
                "psc_name": enriched_result.get("psc_name"),
                "set_aside": enriched_result.get("set_aside"),
                "office": enriched_result.get("office"),
                "city": enriched_result.get("city"),
                "posted_date": enriched_result.get("posted_date"),
                "source_url": enriched_result.get("url"),
                
                # ✅ PURE CAPABILITY SCORE (0-100%)
                "score": round(enriched_result.get("score", 0) * 100),  # Convert 0-1 to 0-100
                "match_score": enriched_result.get("score", 0),  # Keep raw for consistency
            })
        
        # Sort by score descending
        matches.sort(key=lambda x: x["score"], reverse=True)
        
        # Take top 20
        final_matches = matches[:20]
        
        # Calculate average score
        avg_score = round(sum(m["score"] for m in final_matches) / len(final_matches)) if final_matches else 0
        
        logger.info(f"✅ Returning top 20 matches (pure capability scoring)")
        logger.info(f"📊 Average match score: {avg_score}%")
        
        # ============================================================
        # Return results
        # ============================================================
        return QuickStartURLResponse(
            success=True,
            company_name=company_name,
            capabilities_text=capabilities_text,
            capabilities=capabilities,
            matches=final_matches,
            avg_score=avg_score,
            pages_scraped=pages_scraped,
            session_id=session_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quick-start failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Quick-start processing failed: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "feature": "URL Quick-Start",
        "scoring_approach": "Pure capability similarity (Opus approach)"
    }