"""
app/routers/capability_recommendations.py

Standalone router for BidMatch capability recommendations.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict
import logging

from app.database import get_db
from app.services.capability_analyzer_service import CapabilityAnalyzerService
from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings

logger = logging.getLogger(__name__)

# Create router with prefix already included
router = APIRouter(
    prefix="/api/companies",
    tags=["capability-recommendations"]
)


@router.get("/{firm_id}/capability-recommendations")
async def get_capability_recommendations(
    firm_id: str,
    max_recommendations: int = 5,
    db: Session = Depends(get_db)
) -> Dict:
    """
    Analyze capability gaps and return improvement recommendations.
    
    This endpoint:
    1. Queries near-miss contracts (relative ranking)
    2. Extracts capability patterns from contract language
    3. Classifies the company's profile state
    4. Generates 3-5 save-ready capability recommendations
    
    Args:
        firm_id: Company identifier
        max_recommendations: Maximum recommendations to return (default 5)
    
    Returns:
        Dict with analysis_context and recommendations following BidMatch schema
    """
    try:
        logger.info(f"Analyzing capability gaps for firm {firm_id}")
        
        # Initialize services
        pinecone_service = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        analyzer = CapabilityAnalyzerService(db=db, pinecone_service=pinecone_service)
        
        # Run analysis
        result = await analyzer.analyze_capability_gaps(
            firm_id=firm_id,
            max_recommendations=max_recommendations
        )
        
        logger.info(
            f"Generated {len(result.get('recommendations', []))} recommendations "
            f"from {result['analysis_context']['contracts_analyzed']} contracts"
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Error in capability recommendations endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to analyze capability gaps"
        )


@router.get("/{firm_id}/capability-summary")
async def get_capability_summary(
    firm_id: str,
    db: Session = Depends(get_db)
) -> Dict:
    """
    Quick summary for dashboard nudge.
    
    Returns minimal data: count of recommendations and diagnosis.
    Full recommendations fetched separately when user visits Capabilities tab.
    """
    try:
        # Initialize services
        pinecone_service = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        analyzer = CapabilityAnalyzerService(db=db, pinecone_service=pinecone_service)
        
        # Run analysis
        result = await analyzer.analyze_capability_gaps(
            firm_id=firm_id,
            max_recommendations=3  # Just top 3 for summary
        )
        
        # Return lightweight summary
        return {
            "firm_id": firm_id,
            "recommendation_count": len(result.get("recommendations", [])),
            "diagnosis": result["analysis_context"]["profile_diagnosis"],
            "has_recommendations": len(result.get("recommendations", [])) > 0
        }
    
    except Exception as e:
        logger.error(f"Error in capability summary endpoint: {e}")
        return {
            "firm_id": firm_id,
            "recommendation_count": 0,
            "diagnosis": "Unable to analyze",
            "has_recommendations": False
        }