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