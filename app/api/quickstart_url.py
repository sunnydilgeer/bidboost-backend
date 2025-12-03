"""
Quick-start URL endpoint for onboarding via company website
Scrapes website → extracts capabilities → matches contracts
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any
import logging
import uuid

from app.services.web_scraper import WebScraperService
from app.services.pinecone_store import PineconeStoreService
from app.services.llm import LLMService
from app.services.code_lookup import get_code_lookup_service, clean_naics_code
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quickstart", tags=["Quick Start"])

# ========== REQUEST/RESPONSE MODELS ==========

class URLQuickStartRequest(BaseModel):
    """Request model for URL-based quick-start"""
    company_url: str = Field(
        ..., 
        description="Company website URL (e.g., 'acmedefense.com' or 'https://acmedefense.com')"
    )
    
    @validator('company_url')
    def validate_url(cls, v):
        """Basic URL validation"""
        if not v or len(v.strip()) < 4:
            raise ValueError("URL must be at least 4 characters")
        return v.strip()
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_url": "https://acmedefense.com"
            }
        }

class QuickStartContract(BaseModel):
    """Simplified contract result for quick-start"""
    notice_id: str
    title: str
    agency: str
    description: str
    score: float
    
    # Key metadata
    naics_code: str | None = None
    naics_name: str | None = None
    psc_code: str | None = None
    psc_name: str | None = None
    set_aside: str | None = None
    posted_date: str | None = None
    response_deadline: str | None = None
    url: str | None = None
    
    class Config:
        from_attributes = True

class URLQuickStartResponse(BaseModel):
    """Response for URL quick-start"""
    success: bool
    quickstart_id: str  # ✅ ADD THIS
    company_name: str
    capabilities_extracted: str  # Preview of extracted text
    pages_scraped: int
    contracts: List[QuickStartContract]
    total_matches: int
    message: str

# ========== ENDPOINT ==========

@router.post("/url", response_model=URLQuickStartResponse)
async def quickstart_from_url(request: URLQuickStartRequest):
    """
    Quick-start onboarding via company website URL
    
    Flow:
    1. Scrape company website (homepage + key pages)
    2. Extract capabilities text
    3. Generate embedding vector
    4. Query Pinecone for top 20 matches
    5. Return contracts ranked by similarity
    
    This provides instant value without requiring PDF upload or manual data entry.
    Target: <10 seconds from URL to results
    """
    try:
        logger.info(f"🚀 Quick-start URL onboarding: {request.company_url}")
        
        # STEP 1: Scrape website
        scraper = WebScraperService()
        scrape_result = await scraper.scrape_company_website(request.company_url)
        
        if not scrape_result["success"]:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to scrape website: {scrape_result['error']}"
            )
        
        capabilities_text = scrape_result["capabilities_text"]
        company_name = scrape_result["company_name"]
        pages_scraped = scrape_result["pages_scraped"]
        
        if not capabilities_text or len(capabilities_text) < 50:
            raise HTTPException(
                status_code=400,
                detail="Could not extract enough information from website. Please try uploading a PDF instead."
            )
        
        logger.info(f"✅ Scraped {pages_scraped} pages, {len(capabilities_text)} chars")
        
        # STEP 2: Generate embedding
        llm_service = LLMService()
        embedding_vector = await llm_service.generate_embeddings(capabilities_text)
        
        logger.info(f"✅ Generated {len(embedding_vector)}-dim embedding")
        
        # STEP 3: Query Pinecone for matches
        pinecone_service = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        
        matches = pinecone_service.search_contracts(
            query_vector=embedding_vector,
            limit=30,
            min_score=0.3  # Lower threshold to get more candidates
        )
        
        logger.info(f"✅ Found {len(matches)} initial contract matches")
        
        # STEP 3.5: Enhanced multi-factor scoring with realistic distribution
        enhanced_matches = []
        capabilities_words = set(capabilities_text.lower().split())
        
        for match in matches:
            base_score = match["score"]
            boost_reasons = []
            
            # BOOST 1: Keyword overlap between capabilities and contract (up to +12%)
            contract_text = f"{match['title']} {match.get('description', '')}".lower()
            contract_words = set(contract_text.split())
            common_words = capabilities_words & contract_words
            
            # Filter out common stopwords
            stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
            meaningful_overlap = common_words - stopwords
            
            keyword_boost = min(0.12, len(meaningful_overlap) / 80)
            if keyword_boost > 0.08:
                boost_reasons.append(f"Strong keyword overlap")
            
            # BOOST 2: NAICS/PSC code relevance (+8%)
            naics_psc_boost = 0.0
            if match.get("naics_code") or match.get("psc_code"):
                # Industry-specific keyword detection
                tech_keywords = {'software', 'technology', 'it', 'cyber', 'data', 'cloud', 'ai', 'digital'}
                defense_keywords = {'defense', 'aerospace', 'military', 'security', 'surveillance'}
                engineering_keywords = {'engineering', 'construction', 'infrastructure', 'systems'}
                consulting_keywords = {'consulting', 'advisory', 'management', 'strategy', 'training'}
                
                cap_lower = capabilities_text.lower()
                
                if any(kw in cap_lower for kw in tech_keywords):
                    naics_psc_boost = 0.08
                    boost_reasons.append("Tech/IT specialization match")
                elif any(kw in cap_lower for kw in defense_keywords):
                    naics_psc_boost = 0.08
                    boost_reasons.append("Defense/Aerospace match")
                elif any(kw in cap_lower for kw in engineering_keywords):
                    naics_psc_boost = 0.06
                    boost_reasons.append("Engineering capability match")
                elif any(kw in cap_lower for kw in consulting_keywords):
                    naics_psc_boost = 0.05
                    boost_reasons.append("Consulting services match")
            
            # BOOST 3: Title prominence - key terms in contract title (+6%)
            title_boost = 0.0
            title_lower = match.get("title", "").lower()
            # Check if any capability keywords appear in title (high signal)
            important_cap_words = [w for w in capabilities_words if len(w) > 6]  # Longer words are more meaningful
            title_matches = sum(1 for word in important_cap_words if word in title_lower)
            if title_matches >= 2:
                title_boost = 0.06
                boost_reasons.append("Key terms in title")
            
            # Calculate enhanced score with gentle boost and realistic cap
            # Base multiplier: 1.05 (gentle boost)
            # Max final score: 82% (prevents unrealistic 100% matches)
            enhanced_score = min(0.82, (base_score * 1.05) + keyword_boost + naics_psc_boost + title_boost)
            
            # Update match with enhanced score
            match["score"] = enhanced_score
            match["boost_reasons"] = boost_reasons
            enhanced_matches.append(match)
        
        # Sort by enhanced score and take top 20
        enhanced_matches.sort(key=lambda x: x["score"], reverse=True)
        final_matches = enhanced_matches[:20]
        
        logger.info(f"✅ Enhanced scoring complete, returning top 20 matches")
        
        # STEP 4: Enrich with NAICS/PSC descriptions and format results
        code_service = get_code_lookup_service()
        
        contracts = [
            QuickStartContract(
                notice_id=match["notice_id"],
                title=match["title"],
                agency=match["agency"],
                description=match["description"][:500] if match["description"] else "",
                score=match["score"],
                naics_code=clean_naics_code(match.get("naics_code")),  # ✅ CLEAN HERE
                naics_name=code_service.get_naics_name(match.get("naics_code")),
                psc_code=match.get("psc_code"),
                psc_name=code_service.get_psc_name(match.get("psc_code")),
                set_aside=match.get("set_aside"),
                posted_date=match.get("posted_date"),
                response_deadline=match.get("response_deadline"),
                url=match.get("url")
            )
            for match in final_matches
        ]
        
        # Return preview of capabilities (first 500 chars)
        capabilities_preview = capabilities_text[:500] + "..." if len(capabilities_text) > 500 else capabilities_text
        quickstart_id = f"qs_{uuid.uuid4().hex[:12]}"

        return URLQuickStartResponse(
            success=True,
            quickstart_id=quickstart_id,
            company_name=company_name,
            capabilities_extracted=capabilities_preview,
            pages_scraped=pages_scraped,
            contracts=contracts,
            total_matches=len(contracts),
            message=f"Found {len(contracts)} matching contracts from {pages_scraped} pages"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Quick-start URL failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Quick-start failed: {str(e)}"
        )

# ========== HEALTH CHECK ==========

@router.get("/url/health")
async def url_quickstart_health():
    """Check if URL quick-start is available"""
    return {
        "status": "healthy",
        "feature": "URL Quick-Start",
        "max_pages_scraped": 5,
        "timeout_seconds": 10
    }