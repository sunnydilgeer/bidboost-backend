"""
Quick-start URL endpoint for onboarding via company website

Scrapes website → extracts capabilities with LLM → matches contracts

OPUS PURE CAPABILITY APPROACH:
- Uses ContractMatchScorer (SAME as dashboard)
- Creates temporary profile with saved capabilities
- Guaranteed identical scoring to dashboard
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
    Extract capabilities from URL and find matching contracts.
    
    OPUS PURE CAPABILITY APPROACH:
    - Scrapes website
    - Extracts capabilities with LLM
    - Creates temporary profile (deleted after)
    - Uses ContractMatchScorer (SAME as dashboard)
    - Guaranteed identical scoring
    
    Returns:
        - Extracted capabilities (as list of strings)
        - Top 20 matching contracts
        - Pure semantic similarity scores (0-100%)
    """
    
    session_id = str(uuid.uuid4())
    temp_firm_id = f"quickstart-{session_id[:8]}"
    
    logger.info(f"🚀 Quick-start session {temp_firm_id}: Processing URL {request.company_url}")
    
    try:
        from app.database import SessionLocal
        from app.models.company import CompanyProfile, CompanyCapability
        from app.services.capability_store_pinecone import get_capability_store
        from app.services.match_scoring import ContractMatchScorer
        from app.models.contract import Contract
        
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
        capabilities = []
        for cap in capabilities_raw:
            if isinstance(cap, dict):
                text = cap.get("capability_text") or cap.get("text") or ""
                if text:
                    capabilities.append(text)
            elif isinstance(cap, str):
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
        # STEP 3: Create temporary profile with capabilities
        # ============================================================
        logger.info(f"💾 STEP 3: Creating temporary profile")
        
        db = SessionLocal()
        
        try:
            # Create temporary profile
            temp_profile = CompanyProfile(
                firm_id=temp_firm_id,
                company_name=company_name or "Quick Start Company",
                description="Temporary profile for quick-start",
                size="SMALL"
            )
            db.add(temp_profile)
            db.flush()
            
            # Add capabilities to Pinecone and database
            cap_store = get_capability_store()
            
            for cap_text in capabilities[:7]:  # Top 7 capabilities
                # Generate embedding
                cap_vector = await llm.generate_embeddings(cap_text)
                
                # Create capability record
                new_cap = CompanyCapability(
                    company_id=temp_profile.id,
                    capability_text=cap_text,
                    category="General"
                )
                db.add(new_cap)
                db.flush()
                
                # Store in Pinecone
                pinecone_id = await cap_store.add_capability(new_cap, llm)
                new_cap.qdrant_id = pinecone_id
            
            db.commit()
            logger.info(f"✅ Created temp profile with {len(capabilities[:7])} capabilities")
            
            # ============================================================
            # STEP 4: Call SAME scoring logic as dashboard
            # ============================================================
            logger.info(f"🔍 STEP 4: Getting recommendations (IDENTICAL to dashboard)")
            
            pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
            code_service = get_code_lookup_service()
            
            # Generate embedding from combined capabilities
            combined_caps = " ".join(capabilities[:5])
            query_vector = await llm.generate_embeddings(combined_caps)
            
            # Search Pinecone (same as dashboard)
            results = pinecone.search_contracts(
                query_vector=query_vector,
                limit=40,
                min_score=0.35,  # Same threshold as dashboard
                namespace="contracts"
            )
            
            if not results:
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
            
            # Pre-fetch contract vectors (same as dashboard)
            contract_ids = [r.get("id") for r in results if r.get("id")]
            contract_vectors = {}
            
            if contract_ids:
                fetch_result = pinecone.index.fetch(ids=contract_ids, namespace="contracts")
                for vec_id, vec_data in fetch_result.vectors.items():
                    contract_vectors[vec_id] = list(vec_data.values)
                logger.info(f"Pre-fetched {len(contract_vectors)} contract vectors")
            
            # Get capability vectors from Pinecone
            capabilities_data = {}
            saved_caps = db.query(CompanyCapability).filter(
                CompanyCapability.company_id == temp_profile.id
            ).all()
            
            cap_ids = [cap.qdrant_id for cap in saved_caps if cap.qdrant_id]
            if cap_ids:
                capabilities_data = cap_store.get_capabilities_batch(cap_ids)
                logger.info(f"Pre-fetched {len(capabilities_data)} capability vectors")
            
            # Score with ContractMatchScorer (IDENTICAL to dashboard)
            scorer = ContractMatchScorer(db, pinecone.index)
            
            matches = []
            for result in results:
                enriched_result = code_service.enrich_contract(result)
                
                # Create Contract object
                temp_contract = Contract(
                    notice_id=enriched_result.get("notice_id", ""),
                    title=enriched_result.get("title", ""),
                    buyer_name=enriched_result.get("agency", ""),
                    description=enriched_result.get("description", ""),
                    contract_value=enriched_result.get("contract_value"),
                    region=enriched_result.get("state"),
                    qdrant_id=enriched_result.get("id")
                )
                
                # Score with SAME logic as dashboard
                match_scores = scorer.score_contract(
                    temp_contract,
                    temp_firm_id,
                    capability_vectors=capabilities_data,
                    contract_vectors=contract_vectors
                )
                
                if not match_scores or match_scores["match_score"] < 0.35:
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
                    "score": match_scores["match_score"],
                    "match_score": match_scores["match_score"],
                })
            
            # Sort by score descending
            matches.sort(key=lambda x: x["score"], reverse=True)
            final_matches = matches[:20]
            
            if final_matches:
                avg_score = round(sum(m["score"] for m in final_matches) / len(final_matches), 2)
                logger.info(f"✅ Returning {len(final_matches)} matches (IDENTICAL to dashboard)")
                logger.info(f"📊 Average match score: {round(avg_score * 100)}%")
                logger.info(f"   Top 3 scores: {[round(m['score'] * 100) for m in final_matches[:3]]}%")
            
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
            
        finally:
            # Cleanup: Delete temporary profile and capabilities from Pinecone
            try:
                # Delete capability vectors from Pinecone
                saved_caps = db.query(CompanyCapability).filter(
                    CompanyCapability.company_id == temp_profile.id
                ).all()
                
                cap_store = get_capability_store()
                for cap in saved_caps:
                    if cap.qdrant_id:
                        try:
                            cap_store.delete_capability(cap.qdrant_id)
                        except:
                            pass
                
                # Delete from database
                db.query(CompanyCapability).filter(
                    CompanyCapability.company_id == temp_profile.id
                ).delete()
                db.delete(temp_profile)
                db.commit()
                logger.info(f"🧹 Cleaned up temporary profile {temp_firm_id}")
            except Exception as cleanup_error:
                logger.warning(f"Cleanup warning: {cleanup_error}")
            finally:
                db.close()
        
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
        "scoring_approach": "Pure capability similarity - IDENTICAL to dashboard",
        "version": "3.0"
    }