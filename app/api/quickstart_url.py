"""
Quick-start URL endpoint for onboarding via company website

Scrapes website → extracts capabilities with LLM → matches contracts

OPUS PURE CAPABILITY APPROACH:
- Uses ContractMatchScorer (same as dashboard)
- Pure capability similarity (no boosts, no enhancements)
- Consistent scoring across quick-start and dashboard
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from typing import List
import logging
import uuid
import numpy as np

from app.services.web_scraper import WebScraperService
from app.services.llm import LLMService
from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings
from app.services.code_lookup import get_code_lookup_service
from app.services.match_scoring import ContractMatchScorer
from app.models.contract import Contract
from app.database import SessionLocal

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
    quickstart_id: str
    company_name: str
    capabilities_extracted: str
    capabilities: List[str]
    pages_scraped: int
    contracts: List[dict]
    total_matches: int
    message: str

@router.post("/url", response_model=QuickStartURLResponse)
async def quick_start_from_url(request: QuickStartURLRequest):
    """
    Extract capabilities from company URL and find matching contracts.
    
    OPUS PURE CAPABILITY APPROACH:
    - Scrapes website
    - Extracts capabilities with LLM
    - Uses ContractMatchScorer (same as dashboard)
    - Pure capability similarity (no boosts)
    
    Returns:
        - Extracted capabilities (as list of strings)
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
        capabilities_raw = await llm.extract_capabilities(capabilities_text)
        
        if not capabilities_raw:
            raise HTTPException(
                status_code=400,
                detail="Could not extract capabilities from website content"
            )
        
        # ✅ Convert to list of strings (LLM returns list of dicts)
        # Handle both dict format: {"capability_text": "...", "category": "..."}
        # and plain string format (for backwards compatibility)
        capabilities = []
        for cap in capabilities_raw:
            if isinstance(cap, dict):
                # Extract text from dict
                text = cap.get("capability_text") or cap.get("text") or ""
                if text:
                    capabilities.append(text)
            elif isinstance(cap, str):
                # Already a string
                capabilities.append(cap)
        
        if not capabilities:
            raise HTTPException(
                status_code=400,
                detail="Could not extract valid capabilities from website content"
            )
        
        logger.info(f"✅ Extracted {len(capabilities)} capabilities")
        for i, cap in enumerate(capabilities[:5], 1):
            logger.info(f"  {i}. {cap[:60]}...")
        
        # ============================================================
        # STEP 3: Generate embedding for initial search
        # ============================================================
        logger.info(f"🧬 STEP 3: Generating capability embedding")
        
        # Combine top 5 capabilities into single text for embedding
        combined_capabilities = " ".join(capabilities[:5])
        
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
            limit=40,  # Get more candidates for scoring
            min_score=0.35,  # Lower threshold, will re-score
            namespace="contracts"
        )
        
        if not results:
            logger.warning(f"No matching contracts found")
            return QuickStartURLResponse(
                success=True,
                quickstart_id=session_id,
                company_name=company_name,
                capabilities_extracted=capabilities_text,
                capabilities=capabilities,
                pages_scraped=pages_scraped,
                contracts=[],
                total_matches=0,
                message="No matching contracts found"
            )
        
        logger.info(f"✅ Found {len(results)} candidate contracts")
        
        # ============================================================
        # STEP 5: Score contracts using ContractMatchScorer (same as dashboard)
        # ============================================================
        logger.info("📊 STEP 5: Scoring matches with ContractMatchScorer...")
        
        # Create temporary database session
        db = SessionLocal()
        
        try:
            # Pre-fetch contract vectors in batch
            contract_ids = [r.get("id") for r in results if r.get("id")]
            contract_vectors = {}
            
            if contract_ids:
                fetch_result = pinecone.index.fetch(ids=contract_ids, namespace="contracts")
                for vec_id, vec_data in fetch_result.vectors.items():
                    contract_vectors[vec_id] = list(vec_data.values)
                logger.info(f"Pre-fetched {len(contract_vectors)} contract vectors")
            
            # Generate temporary capability vectors from extracted capabilities
            temp_capability_vectors = {}
            for i, cap_text in enumerate(capabilities[:7]):  # Use top 7 like dashboard
                cap_vector = await llm.generate_embeddings(cap_text)
                temp_capability_vectors[f"temp_{i}"] = cap_vector
            
            logger.info(f"Generated {len(temp_capability_vectors)} capability vectors")
            
            # Initialize scorer
            scorer = ContractMatchScorer(db, pinecone.index)
            
            matches = []
            for result in results:
                enriched_result = code_service.enrich_contract(result)
                
                # Get contract vector
                contract_id = enriched_result.get("id")
                contract_vector = contract_vectors.get(contract_id)
                
                if not contract_vector:
                    logger.warning(f"No vector for contract {contract_id}")
                    continue
                
                # Calculate similarities with all capabilities
                similarities = []
                for cap_vector in temp_capability_vectors.values():
                    similarity = scorer._cosine_similarity(contract_vector, cap_vector)
                    similarities.append(similarity)
                
                if not similarities:
                    continue
                
                # ✅ Use BEST match (Opus approach - same as dashboard)
                capability_score = float(np.max(similarities))
                
                # Only include if score >= 40%
                if capability_score < 0.40:
                    continue
                
                matches.append({
                    "notice_id": enriched_result.get("notice_id", ""),
                    "title": enriched_result.get("title", ""),
                    "agency": enriched_result.get("agency", ""),
                    "description": enriched_result.get("description", ""),
                    "contract_value": enriched_result.get("contract_value"),
                    "region": enriched_result.get("state"),
                    "response_deadline": enriched_result.get("response_deadline"),
                    "naics_code": enriched_result.get("naics_code"),
                    "naics_name": enriched_result.get("naics_name"),
                    "psc_code": enriched_result.get("psc_code"),
                    "psc_name": enriched_result.get("psc_name"),
                    "set_aside": enriched_result.get("set_aside"),
                    "office": enriched_result.get("office"),
                    "city": enriched_result.get("city"),
                    "posted_date": enriched_result.get("posted_date"),
                    "url": enriched_result.get("url"),
                    
                    # ✅ Use calculated capability score (same as dashboard)
                    "score": capability_score,
                    "match_score": capability_score,
                })
            
            # Sort by score descending
            matches.sort(key=lambda x: x["score"], reverse=True)
            
            # Take top 20
            final_matches = matches[:20]
            
            if final_matches:
                # Calculate average score
                avg_score = round(sum(m["score"] for m in final_matches) / len(final_matches), 2)
                
                logger.info(f"✅ Returning top {len(final_matches)} matches (pure capability scoring)")
                logger.info(f"📊 Average match score: {round(avg_score * 100)}%")
                logger.info(f"   Top 3 scores: {[round(m['score'] * 100) for m in final_matches[:3]]}%")
            
        finally:
            db.close()
        
        # ============================================================
        # Return results
        # ============================================================
        return QuickStartURLResponse(
            success=True,
            quickstart_id=session_id,
            company_name=company_name,
            capabilities_extracted=capabilities_text,
            capabilities=capabilities,
            pages_scraped=pages_scraped,
            contracts=final_matches,
            total_matches=len(final_matches),
            message=f"Found {len(final_matches)} matching contracts"
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
        "scoring_approach": "Pure capability similarity (Opus approach) - matches dashboard",
        "version": "2.1"
    }