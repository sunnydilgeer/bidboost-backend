"""
Incumbent Matcher Service

Identifies incumbent contractors and provides strategic intelligence:
- Who currently holds similar contracts (incumbent detection)
- Typical award amounts (pricing benchmarks)
- Competition levels (average number of bidders)
"""

import logging
from typing import Dict, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from datetime import datetime, timedelta
from app.models.company import OpportunityChain
from app.models.contract_awards import ContractAward

logger = logging.getLogger(__name__)


class IncumbentMatcher:
    """Service for finding incumbent contractors and analyzing competition."""
    
    def __init__(self, db: Session, vector_client):
        self.db = db
        
        # Auto-detect client type (Pinecone or Qdrant)
        if hasattr(vector_client, "fetch"):
            self.pinecone_index = vector_client
            self.using_pinecone = True
        else:
            self.qdrant_client = vector_client
            self.using_pinecone = False
    
    def _normalize_agency_name(self, agency_name: str) -> str:
        """
        Map SAM.gov sub-agencies to USASpending parent agencies.
        
        SAM.gov uses specific agencies (DEPT OF THE ARMY)
        USASpending uses parent agencies (Department of Defense)
        """
        if not agency_name:
            return ""
        
        agency_lower = agency_name.lower()
        
        # Department of Defense sub-agencies
        dod_keywords = [
            'army', 'navy', 'air force', 'marine', 'darpa', 'defense logistics',
            'defense health', 'defense information', 'dod', 'dept of defense',
            'missile defense', 'defense advanced', 'national security agency',
            'defense intelligence', 'special operations'
        ]
        
        if any(keyword in agency_lower for keyword in dod_keywords):
            return "Department of Defense"
        
        # Department of Homeland Security sub-agencies
        dhs_keywords = ['customs', 'ice', 'tsa', 'fema', 'secret service', 'coast guard']
        if any(keyword in agency_lower for keyword in dhs_keywords):
            return "Department of Homeland Security"
        
        # Department of Health and Human Services
        hhs_keywords = ['hhs', 'nih', 'cdc', 'fda', 'health and human']
        if any(keyword in agency_lower for keyword in hhs_keywords):
            return "Department of Health and Human Services"
        
        # NASA (usually consistent)
        if 'nasa' in agency_lower or 'aeronautics and space' in agency_lower:
            return "National Aeronautics and Space Administration"
        
        # GSA
        if 'gsa' in agency_lower or 'general services' in agency_lower:
            return "General Services Administration"
        
        # Department of Veterans Affairs
        if 'veteran' in agency_lower or 'va ' in agency_lower:
            return "Department of Veterans Affairs"
        
        # Department of Transportation sub-agencies
        dot_keywords = ['faa', 'federal aviation', 'highway', 'transportation']
        if any(keyword in agency_lower for keyword in dot_keywords):
            return "Department of Transportation"
        
        # Department of Agriculture
        if 'agriculture' in agency_lower or 'usda' in agency_lower:
            return "Department of Agriculture"
        
        # EPA
        if 'epa' in agency_lower or 'environmental protection' in agency_lower:
            return "Environmental Protection Agency"
        
        # Department of the Interior
        if 'interior' in agency_lower:
            return "Department of the Interior"
        
        # If no mapping found, return original
        return agency_name
    
    def _normalize_naics_code(self, naics_code: str) -> str:
        """
        Normalize NAICS code to 6-digit format.
        
        SAM.gov sometimes has 5 digits (e.g., "81121")
        USASpending has 6 digits (e.g., "811210")
        
        We pad with trailing zero if needed.
        """
        if not naics_code:
            return ""
        
        # Remove any whitespace
        naics = naics_code.strip()
        
        # Pad to 6 digits with trailing zero if needed
        if len(naics) == 5:
            return naics + "0"
        elif len(naics) == 4:
            return naics + "00"
        elif len(naics) == 3:
            return naics + "000"
        
        return naics
    
    def find_incumbent(self, opportunity_chain: OpportunityChain) -> Optional[Dict]:
        """
        Find the incumbent contractor for this opportunity.
        
        Returns incumbent info if found:
        - incumbent_name: str
        - award_amount: float
        - contract_start: date
        - contract_end: date
        - is_recompete: bool (contract ending within 180 days)
        - confidence: "high" | "medium" | "low"
        """
        
        if not opportunity_chain or not opportunity_chain.base_notice_id:
            return None
        
        try:
            # Strategy 1: Exact match by solicitation number (PIID)
            # Look for award with matching PIID
            award = self.db.query(ContractAward).filter(
                ContractAward.piid == opportunity_chain.base_notice_id
            ).first()
            
            if award:
                is_recompete = False
                if award.contract_end_date:
                    days_until_end = (award.contract_end_date - datetime.now().date()).days
                    is_recompete = 0 <= days_until_end <= 180
                
                return {
                    "incumbent_name": award.awardee_name,
                    "award_amount": float(award.award_amount) if award.award_amount else None,
                    "contract_start": award.contract_start_date.isoformat() if award.contract_start_date else None,
                    "contract_end": award.contract_end_date.isoformat() if award.contract_end_date else None,
                    "is_recompete": is_recompete,
                    "confidence": "high"
                }
            
            # Strategy 2: Fuzzy match by agency + NAICS + semantic similarity
            # Get opportunity vector
            if not opportunity_chain.pinecone_id:
                return None
            
            # Fetch opportunity vector from Pinecone
            opp_vector = None
            if self.using_pinecone:
                result = self.pinecone_index.fetch(
                    ids=[opportunity_chain.pinecone_id],
                    namespace="opportunity_chains"
                )
                if result.vectors and opportunity_chain.pinecone_id in result.vectors:
                    opp_vector = list(result.vectors[opportunity_chain.pinecone_id].values)
            
            if not opp_vector:
                return None
            
            # Find similar awards
            similar_awards = self._find_similar_awards(
                opp_vector,
                opportunity_chain.agency_name,
                opportunity_chain.naics_code
            )
            
            if similar_awards and len(similar_awards) > 0:
                # Return most recent award as incumbent
                most_recent = similar_awards[0]
                
                return {
                    "incumbent_name": most_recent["awardee_name"],
                    "award_amount": most_recent["award_amount"],
                    "contract_start": most_recent["contract_start"],
                    "contract_end": most_recent["contract_end"],
                    "is_recompete": most_recent.get("is_recompete", False),
                    "confidence": "medium" if most_recent["similarity"] > 0.6 else "low"
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding incumbent for {opportunity_chain.base_notice_id}: {e}")
            return None
    
    def _find_similar_awards(
        self,
        query_vector: List[float],
        agency_name: str,
        naics_code: str,
        limit: int = 5
    ) -> List[Dict]:
        """
        Find similar contract awards using vector similarity.
        
        Returns list of awards sorted by similarity score.
        """
        
        # TODO: Implement vector search against embedded contract awards
        # For now, just query by agency + NAICS
        
        normalized_agency = self._normalize_agency_name(agency_name)
        normalized_naics = self._normalize_naics_code(naics_code)
        
        awards = self.db.query(ContractAward).filter(
            and_(
                ContractAward.agency_name == normalized_agency,
                ContractAward.naics_code == normalized_naics,
                ContractAward.award_date.isnot(None)
            )
        ).order_by(ContractAward.award_date.desc()).limit(limit).all()
        
        results = []
        for award in awards:
            is_recompete = False
            if award.contract_end_date:
                days_until_end = (award.contract_end_date - datetime.now().date()).days
                is_recompete = 0 <= days_until_end <= 180
            
            results.append({
                "awardee_name": award.awardee_name,
                "award_amount": float(award.award_amount) if award.award_amount else None,
                "contract_start": award.contract_start_date.isoformat() if award.contract_start_date else None,
                "contract_end": award.contract_end_date.isoformat() if award.contract_end_date else None,
                "is_recompete": is_recompete,
                "similarity": 0.5  # Placeholder - would calculate from vectors
            })
        
        return results
    
    def get_pricing_benchmarks(self, naics_code: str, agency_name: str) -> Dict:
        """
        Get pricing benchmarks for similar contracts.
        
        Returns:
        - avg_award: float
        - min_award: float
        - max_award: float
        - median_award: float (optional)
        - sample_size: int
        """
        
        from sqlalchemy import func
        
        # ✅ Normalize both agency AND NAICS
        normalized_agency = self._normalize_agency_name(agency_name)
        normalized_naics = self._normalize_naics_code(naics_code)
        
        awards = self.db.query(
            func.avg(ContractAward.award_amount).label('avg'),
            func.min(ContractAward.award_amount).label('min'),
            func.max(ContractAward.award_amount).label('max'),
            func.count().label('count')
        ).filter(
            and_(
                ContractAward.naics_code == normalized_naics,
                ContractAward.agency_name == normalized_agency,
                ContractAward.award_amount.isnot(None),
                ContractAward.award_amount > 0
            )
        ).first()
        
        # Require minimum 3 samples for reliability
        if not awards or awards.count < 3:
            return {}
        
        return {
            "avg_award": float(awards.avg) if awards.avg else None,
            "min_award": float(awards.min) if awards.min else None,
            "max_award": float(awards.max) if awards.max else None,
            "median_award": None,  # Would need percentile_cont function
            "sample_size": awards.count
        }
    
    def get_competition_stats(self, naics_code: str, agency_name: str) -> Dict:
        """
        Get competition statistics for similar contracts.
        
        Returns:
        - avg_offers: float (average number of bidders)
        - max_offers: int
        - set_aside_distribution: dict
        """
        
        from sqlalchemy import func
        
        # ✅ Normalize both agency AND NAICS
        normalized_agency = self._normalize_agency_name(agency_name)
        normalized_naics = self._normalize_naics_code(naics_code)
        
        competition = self.db.query(
            func.avg(ContractAward.number_of_offers).label('avg_offers'),
            func.max(ContractAward.number_of_offers).label('max_offers')
        ).filter(
            and_(
                ContractAward.naics_code == normalized_naics,
                ContractAward.agency_name == normalized_agency,
                ContractAward.number_of_offers.isnot(None)
            )
        ).first()
        
        # Get set-aside distribution
        set_asides = self.db.query(
            ContractAward.set_aside_type,
            func.count().label('count')
        ).filter(
            and_(
                ContractAward.naics_code == normalized_naics,
                ContractAward.agency_name == normalized_agency,
                ContractAward.set_aside_type.isnot(None)
            )
        ).group_by(ContractAward.set_aside_type).all()
        
        set_aside_dist = {sa.set_aside_type: sa.count for sa in set_asides}
        
        return {
            "avg_offers": float(competition.avg_offers) if competition and competition.avg_offers else None,
            "max_offers": competition.max_offers if competition else None,
            "set_aside_distribution": set_aside_dist
        }