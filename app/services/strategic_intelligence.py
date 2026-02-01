# app/services/strategic_intelligence.py
from sqlalchemy.orm import Session
from typing import Dict, Optional
from app.models.opportunities import OpportunityChain
from app.services.incumbent_matcher import IncumbentMatcher
import logging

logger = logging.getLogger(__name__)

class StrategicIntelligenceService:
    """
    Coordinates strategic intelligence gathering for contract opportunities.
    Combines incumbent tracking, pricing benchmarks, and competition analysis.
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.incumbent_matcher = IncumbentMatcher(db)
    
    def get_contract_intelligence(
        self, 
        opportunity: OpportunityChain
    ) -> Dict:
        """
        Get comprehensive strategic intelligence for an opportunity.
        
        Returns:
        {
            "incumbent": {
                "incumbent_name": str,
                "award_amount": float,
                "contract_end": str,
                "is_recompete": bool,
                "confidence": str
            } or None,
            "pricing_benchmarks": {
                "avg_award": float,
                "min_award": float,
                "max_award": float,
                "median_award": float,
                "sample_size": int
            } or None,
            "competition_stats": {
                "avg_offers": float,
                "max_offers": int,
                "set_aside_distribution": dict,
                "sample_size": int
            } or None,
            "re_compete_alert": bool
        }
        """
        try:
            # Get incumbent information
            incumbent = self.incumbent_matcher.find_incumbent(opportunity)
            
            # Get pricing benchmarks (requires NAICS + agency)
            pricing = None
            if opportunity.base_naics and opportunity.base_agency:
                pricing = self.incumbent_matcher.get_pricing_benchmarks(
                    opportunity.base_naics,
                    opportunity.base_agency
                )
            
            # Get competition statistics
            competition = None
            if opportunity.base_naics and opportunity.base_agency:
                competition = self.incumbent_matcher.get_competition_stats(
                    opportunity.base_naics,
                    opportunity.base_agency
                )
            
            # Determine if this is a re-compete situation
            re_compete_alert = (
                incumbent is not None and 
                incumbent.get('is_recompete', False)
            )
            
            return {
                "incumbent": incumbent,
                "pricing_benchmarks": pricing,
                "competition_stats": competition,
                "re_compete_alert": re_compete_alert
            }
            
        except Exception as e:
            logger.error(f"Error getting strategic intelligence: {e}")
            return {
                "incumbent": None,
                "pricing_benchmarks": None,
                "competition_stats": None,
                "re_compete_alert": False
            }