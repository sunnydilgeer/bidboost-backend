"""
SAM.GOV Contract Search API Routes
Clean, focused routes for US federal contract opportunities with match scoring
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService
from app.core.auth import User, get_current_active_user
from app.database import get_db
from app.models.contract import Contract
from app.models.company import CompanyProfile
from app.services.sam_match_scoring import SAMContractMatchScorer
from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sam", tags=["SAM.GOV Contracts"])


# ========== HELPER FUNCTIONS ==========

def get_vector_store():
    """Get vector store instance (Pinecone or Qdrant)"""
    if settings.USE_PINECONE:
        return PineconeStoreService(api_key=settings.PINECONE_API_KEY)
    else:
        return VectorStoreService()


def get_llm_service():
    """Get LLMService instance"""
    return LLMService()


# ========== REQUEST/RESPONSE MODELS ==========

class SAMSearchRequest(BaseModel):
    query: str
    limit: int = 20
    min_score: Optional[float] = 0.0


class MatchScoresBreakdown(BaseModel):
    """Match score breakdown for frontend display"""
    capability_score: float
    past_win_score: float
    preference_score: float
    total_score: float


class SAMContractResult(BaseModel):
    # Core fields
    notice_id: str
    title: str
    description: str
    buyer_name: str
    region: Optional[str]
    closing_date: Optional[str]
    published_date: Optional[str]
    
    # SAM-specific fields
    solicitation_number: Optional[str]
    set_aside: Optional[str]
    set_aside_code: Optional[str]
    opportunity_type: Optional[str]
    psc_code: Optional[str]
    contact_name: Optional[str]
    contact_phone: Optional[str]
    place_of_performance: Optional[str]
    source_url: Optional[str]
    
    # Contract details
    award_number: Optional[str]
    award_date: Optional[str]
    awardee: Optional[str]
    
    # Scoring
    score: float
    total_match_score: Optional[float]
    match_scores: Optional[MatchScoresBreakdown] = None
    match_reasons: Optional[List[str]] = None


class SAMSearchResponse(BaseModel):
    query: str
    results: List[SAMContractResult]
    total_found: int


class SAMStatsResponse(BaseModel):
    total_contracts: int
    contracts_by_agency: dict
    urgent_contracts: int


def format_sam_contract(result: dict, match_scores: Optional[dict] = None) -> dict:
    """Format search result into SAMContractResult structure"""
    
    formatted = {
        "notice_id": result.get('notice_id', ''),
        "title": result.get('title', ''),
        "description": result.get('description', ''),
        "buyer_name": result.get('agency', ''),  # Pinecone uses 'agency'
        "region": result.get('state', ''),
        "closing_date": result.get('response_deadline', ''),
        "published_date": result.get('posted_date', ''),
        "solicitation_number": None,
        "set_aside": result.get('set_aside', ''),
        "set_aside_code": None,
        "opportunity_type": None,
        "psc_code": result.get('naics_code', ''),
        "contact_name": None,
        "contact_phone": None,
        "place_of_performance": None,
        "source_url": result.get('url', ''),
        "award_number": None,
        "award_date": None,
        "awardee": None,
        "score": result.get('score', 0.0),
    }
    
    if match_scores:
        formatted["total_match_score"] = match_scores['total_score']
        formatted["match_scores"] = {
            'capability_score': match_scores['capability_score'],
            'past_win_score': match_scores['past_performance_score'],
            'preference_score': match_scores['preference_score'],
            'total_score': match_scores['total_score']
        }
        formatted["match_reasons"] = match_scores['match_reasons']
    else:
        formatted["total_match_score"] = result.get('score', 0.0)
    
    return formatted


# ========== SEARCH ENDPOINTS ==========

@router.post("/search", response_model=SAMSearchResponse)
async def search_sam_contracts(
    request: SAMSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Search SAM.GOV contracts with semantic similarity"""
    try:
        vector_store = get_vector_store()
        llm_service = get_llm_service()
        
        # Generate query embedding
        query_vector = await llm_service.generate_embeddings(request.query)
        
        # Search in Pinecone/Qdrant
        search_results = vector_store.search_contracts(
            query_vector=query_vector,
            limit=request.limit,
            min_score=request.min_score
        )
        
        formatted_results = []
        for result in search_results:
            formatted_contract = format_sam_contract(result)
            formatted_results.append(SAMContractResult(**formatted_contract))
        
        logger.info(f"SAM search '{request.query}' by {current_user.email}: {len(formatted_results)} results")
        
        return SAMSearchResponse(
            query=request.query,
            results=formatted_results,
            total_found=len(formatted_results)
        )
        
    except Exception as e:
        logger.error(f"SAM search failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/recommended", response_model=SAMSearchResponse)
async def get_personalized_sam_recommendations(
    limit: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get personalized contract recommendations using semantic matching.
    
    This endpoint provides the single source of truth for personalized results
    across Dashboard and Contracts-US pages.
    
    Process:
    1. Load user's capability embeddings from Qdrant
    2. Search Pinecone using each capability vector
    3. Deduplicate and aggregate results
    4. Score with SAMContractMatchScorer (capability + past wins + preferences)
    5. Return top matches sorted by total score
    """
    try:
        from qdrant_client import QdrantClient
        
        logger.info(f"🎯 Generating SAM recommendations for {current_user.email}")
        
        # Get company profile with capabilities
        profile = db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == current_user.firm_id
        ).first()
        
        if not profile or not profile.capabilities:
            logger.warning(f"No capabilities found for user {current_user.email}")
            return SAMSearchResponse(query="", results=[], total_found=0)
        
        # Initialize services - Pinecone for contracts, Qdrant for capabilities
        pinecone_store = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        qdrant_client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )
        
        # STEP 1: Get capability embeddings and search Pinecone
        all_contract_ids = {}  # Deduplicate by notice_id, keep highest score
        capabilities_used = 0
        
        for cap in profile.capabilities[:5]:  # Top 5 capabilities
            if not cap.qdrant_id:
                continue
                
            try:
                # Retrieve capability vector from Qdrant
                cap_points = qdrant_client.retrieve(
                    collection_name="capabilities",
                    ids=[cap.qdrant_id],
                    with_vectors=True
                )
                
                if not cap_points or not cap_points[0].vector:
                    logger.warning(f"No vector found for capability {cap.qdrant_id}")
                    continue
                
                # Search Pinecone using capability vector
                results = pinecone_store.search_contracts(
                    query_vector=cap_points[0].vector,
                    limit=limit,
                    min_score=0.3  # Minimum semantic similarity threshold
                )
                
                capabilities_used += 1
                
                # Deduplicate - keep highest scoring match per contract
                for r in results:
                    notice_id = r.get('notice_id')
                    if notice_id:
                        score = r.get('score', 0)
                        if notice_id not in all_contract_ids or score > all_contract_ids[notice_id].get('score', 0):
                            all_contract_ids[notice_id] = r
                
                logger.info(f"  ✅ Capability '{cap.capability_text[:40]}...' → {len(results)} contracts (similarity: {results[0].get('score', 0):.2%} top)")
            
            except Exception as e:
                logger.error(f"Failed to process capability {cap.qdrant_id}: {e}")
                continue
        
        if not all_contract_ids:
            logger.warning(f"No contracts found for user {current_user.email}")
            return SAMSearchResponse(query="", results=[], total_found=0)
        
        # STEP 2: Score all found contracts with SAMContractMatchScorer
        scorer = SAMContractMatchScorer(db, qdrant_client)
        scored_results = []
        
        for result in all_contract_ids.values():
            try:
                # Create temporary Contract object for scoring
                temp_contract = Contract(
                    notice_id=result.get('notice_id', ''),
                    title=result.get('title', ''),
                    buyer_name=result.get('agency', ''),
                    description=result.get('description', ''),
                    contract_value=result.get('contract_value'),
                    region=result.get('state'),
                    qdrant_id=result.get('id')  # Pinecone ID for vector lookup
                )
                
                # Score with full matcher (capability + past wins + preferences + set-asides)
                match_scores = scorer.score_contract(
                    temp_contract,
                    current_user.firm_id,
                    sam_metadata={
                        'set_aside_code': result.get('set_aside'),
                        'naics_code': result.get('naics_code'),
                        'department': result.get('agency')
                    }
                )
                
                # Only include if passes filters
                if match_scores:
                    formatted = format_sam_contract(result, match_scores)
                    scored_results.append(SAMContractResult(**formatted))
            
            except Exception as e:
                logger.error(f"Failed to score contract {result.get('notice_id')}: {e}")
                continue
        
        # STEP 3: Sort by total match score
        scored_results.sort(key=lambda x: x.total_match_score or 0, reverse=True)
        final_results = scored_results[:limit]
        
        # Log summary
        logger.info(f"🎉 Recommendations complete:")
        logger.info(f"   Used {capabilities_used} capability embeddings")
        logger.info(f"   Found {len(all_contract_ids)} unique contracts")
        logger.info(f"   Scored {len(scored_results)} contracts")
        logger.info(f"   Returning top {len(final_results)} matches")
        if final_results:
            logger.info(f"   Top match: '{final_results[0].title[:50]}...' ({final_results[0].total_match_score:.0%})")
        
        return SAMSearchResponse(
            query="",  # No text query - pure semantic matching
            results=final_results,
            total_found=len(final_results)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SAM recommendations failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate recommendations: {str(e)}")


@router.get("/contracts/{notice_id}")
async def get_sam_contract_details(
    notice_id: str,
    current_user: User = Depends(get_current_active_user)
):
    """Get full details for a specific contract"""
    try:
        vector_store = get_vector_store()
        contract = vector_store.get_by_id(notice_id)
        
        if not contract:
            raise HTTPException(status_code=404, detail=f"Contract {notice_id} not found")
        
        return contract
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get contract {notice_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve contract: {str(e)}")


@router.get("/stats", response_model=SAMStatsResponse)
async def get_sam_stats(current_user: User = Depends(get_current_active_user)):
    """Get statistics about contracts in database"""
    try:
        vector_store = get_vector_store()
        total = vector_store.get_document_count()
        
        return SAMStatsResponse(
            total_contracts=total,
            contracts_by_agency={},  # TODO: Implement agency aggregation
            urgent_contracts=0  # TODO: Implement date filtering
        )
        
    except Exception as e:
        logger.error(f"Failed to get SAM stats: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve stats: {str(e)}")


@router.get("/health")
async def sam_health_check():
    """Health check for SAM.GOV search service"""
    try:
        vector_store = get_vector_store()
        count = vector_store.get_document_count()
        
        return {
            "status": "healthy",
            "service": "SAM.GOV Search API",
            "contracts_available": count,
            "vector_store": "Pinecone" if settings.USE_PINECONE else "Qdrant"
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }