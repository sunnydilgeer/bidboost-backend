from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference
from app.models.contract import Contract
from qdrant_client import QdrantClient
import numpy as np
import logging

logger = logging.getLogger(__name__)


class ContractMatchScorer:
    """
    Scores contract opportunities against company profiles using:
    - Semantic similarity between capabilities and contract requirements
    - Past win matching (similar buyers, contract values)
    - Search preference filtering (value ranges, regions, keywords)
    """
    
    def __init__(self, db: Session, qdrant_client: QdrantClient):
        self.db = db
        self.qdrant = qdrant_client
    
    def score_contract(self, contract: Contract, firm_id: str) -> Optional[Dict]:
        """
        Calculate relevance score for a contract against company profile.
        
        Returns None if contract fails hard filters (excluded categories, value range).
        Returns dict with scores and match reasons if contract passes filters.
        """
        
        # Load company profile with relationships
        profile = self.db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == firm_id
        ).first()
        
        if not profile:
            logger.debug(f"No company profile found for firm {firm_id}")
            return None
        
        # Initialize score structure
        scores = {
            "capability_score": 0.0,
            "past_win_score": 0.0,
            "preference_score": 0.0,
            "total_score": 0.0,
            "match_reasons": []
        }
        
        # 1. Capability Matching (40% weight) - Semantic similarity
        capability_score = self._calculate_capability_score(contract, profile.capabilities)
        scores["capability_score"] = capability_score
        if capability_score > 0.6:
            scores["match_reasons"].append(f"Strong capability match ({capability_score:.0%})")
        elif capability_score > 0.4:
            scores["match_reasons"].append(f"Good capability match ({capability_score:.0%})")
        elif capability_score > 0.25:
            scores["match_reasons"].append(f"Moderate capability match ({capability_score:.0%})")
        
        # 2. Past Win Matching (30% weight) - Similar contracts won
        past_win_score, win_reasons = self._calculate_past_win_score(contract, profile.past_wins)
        scores["past_win_score"] = past_win_score
        scores["match_reasons"].extend(win_reasons)
        
        # 3. Search Preference Filtering (30% weight)
        preference_score, passes_filters, pref_reasons = self._calculate_preference_score(
            contract, profile.search_preference
        )
        scores["preference_score"] = preference_score
        scores["match_reasons"].extend(pref_reasons)
        
        # Don't return contracts that fail hard filters
        if not passes_filters:
            logger.debug(f"Contract {contract.notice_id} failed preference filters")
            return None
        
        # Calculate weighted total score
        scores["total_score"] = (
            capability_score * 0.4 +
            past_win_score * 0.3 +
            preference_score * 0.3
        )
        
        logger.info(f"Contract {contract.notice_id} scored {scores['total_score']:.2%} for firm {firm_id}")
        
        return scores
    
    def _calculate_capability_score(
        self, 
        contract: Contract, 
        capabilities: List[CompanyCapability]
    ) -> float:
        """Use semantic similarity between capabilities and contract description"""
        if not capabilities or not contract.qdrant_id:
            logger.debug(f"Missing capabilities ({len(capabilities)}) or contract qdrant_id ({contract.qdrant_id})")
            return 0.0
        
        try:
            # 🔧 FIX: Get contract embedding from Qdrant WITH VECTORS
            contract_points = self.qdrant.retrieve(
                collection_name="legal_documents",
                ids=[contract.qdrant_id],
                with_vectors=True  # ← CRITICAL FIX
            )
            
            if not contract_points:
                logger.warning(f"Contract {contract.qdrant_id} not found in Qdrant")
                return 0.0
            
            contract_vector = contract_points[0].vector
            
            # Calculate similarity with each capability and take the best matches
            similarities = []
            for cap in capabilities:
                if cap.qdrant_id:
                    # 🔧 FIX: Get capability embedding WITH VECTORS
                    cap_points = self.qdrant.retrieve(
                        collection_name="capabilities",
                        ids=[cap.qdrant_id],
                        with_vectors=True  # ← CRITICAL FIX
                    )
                    if cap_points:
                        cap_vector = cap_points[0].vector
                        similarity = self._cosine_similarity(contract_vector, cap_vector)
                        similarities.append(similarity)
                        logger.debug(f"Capability '{cap.capability_text[:50]}' similarity: {similarity:.3f}")
            
            if not similarities:
                return 0.0
            
            # 🎯 IMPROVEMENT: Use average of top 3 matches instead of just max
            # This rewards having multiple relevant capabilities
            similarities.sort(reverse=True)
            top_matches = similarities[:3]
            avg_score = sum(top_matches) / len(top_matches)
            
            logger.info(f"Capability score: {avg_score:.3f} (from {len(similarities)} capabilities)")
            return avg_score
        
        except Exception as e:
            logger.error(f"Capability scoring error: {str(e)}", exc_info=True)
            return 0.0
    
    def _calculate_past_win_score(
        self, 
        contract: Contract, 
        past_wins: List[PastWin]
    ) -> tuple[float, List[str]]:
        """
        Score based on similar past wins.
        Returns (score, list of match reasons).
        """
        if not past_wins:
            return 0.0, []
        
        score = 0.0
        reasons = []
        
        for win in past_wins:
            # Match by buyer organization (exact or partial match)
            if contract.buyer_name and win.buyer_name:
                buyer_lower = contract.buyer_name.lower()
                win_buyer_lower = win.buyer_name.lower()
                
                if win_buyer_lower == buyer_lower:
                    score += 0.6
                    reasons.append(f"Previously won contract with {win.buyer_name}")
                elif win_buyer_lower in buyer_lower or buyer_lower in win_buyer_lower:
                    score += 0.4
                    reasons.append(f"Previously worked with similar buyer ({win.buyer_name})")
            
            # Match by contract value range (within 2x)
            if contract.contract_value and win.contract_value:
                # Convert to float to avoid Decimal/float mixing
                contract_val = float(contract.contract_value)
                win_val = float(win.contract_value)
                
                value_ratio = min(contract_val, win_val) / max(contract_val, win_val)
                if value_ratio > 0.5:  # Within 2x range
                    score += 0.3
                    if value_ratio > 0.8:  # Very similar value
                        reasons.append(f"Similar contract value to past win (£{win.contract_value:,.0f})")
        
        # Cap score at 1.0
        final_score = min(score, 1.0)
        
        return final_score, reasons
    
    def _calculate_preference_score(
        self, 
        contract: Contract, 
        preferences: Optional[SearchPreference]
    ) -> tuple[float, bool, List[str]]:
        """
        Apply search preferences as filters and scoring.
        
        Returns:
            - score (float): Preference match score 0-1
            - passes_filters (bool): Whether contract passes hard filters
            - reasons (List[str]): Match reasons for display
        """
        if not preferences:
            return 1.0, True, []  # No preferences = pass all
        
        passes_filters = True
        score = 1.0
        reasons = []
        
        # ===== HARD FILTERS (fail contract if not met) =====
        
        # Value range filter
        if contract.contract_value:
            if preferences.min_contract_value and contract.contract_value < preferences.min_contract_value:
                passes_filters = False
                logger.debug(f"Contract value £{contract.contract_value:,.0f} below minimum £{preferences.min_contract_value:,.0f}")
            
            if preferences.max_contract_value and contract.contract_value > preferences.max_contract_value:
                passes_filters = False
                logger.debug(f"Contract value £{contract.contract_value:,.0f} above maximum £{preferences.max_contract_value:,.0f}")
            
            # Add reason if value is in range
            if passes_filters and (preferences.min_contract_value or preferences.max_contract_value):
                reasons.append(f"Contract value (£{contract.contract_value:,.0f}) matches preferences")
        
        # Excluded categories filter (HARD)
        if preferences.excluded_categories:
            contract_text = f"{contract.title} {contract.description or ''}".lower()
            for category in preferences.excluded_categories:
                if category.lower() in contract_text:
                    passes_filters = False
                    logger.debug(f"Contract contains excluded category: {category}")
                    break
        
        # ===== SOFT FILTERS (reduce/boost score) =====
        
        # Region preference (SOFT - reduce score if no match)
        if preferences.preferred_regions and contract.region:
            if contract.region in preferences.preferred_regions:
                score += 0.2  # Boost for preferred region
                reasons.append(f"Located in preferred region ({contract.region})")
            else:
                score *= 0.6  # Penalty for non-preferred region
        
        # Keyword matching (SOFT - boost score for matches)
        if preferences.keywords:
            contract_text = f"{contract.title} {contract.description or ''}".lower()
            matched_keywords = [kw for kw in preferences.keywords if kw.lower() in contract_text]
            
            if matched_keywords:
                keyword_boost = len(matched_keywords) * 0.15
                score += keyword_boost
                reasons.append(f"Matches keywords: {', '.join(matched_keywords[:3])}")
        
        # Cap final score at 1.0
        final_score = min(score, 1.0)
        
        return final_score, passes_filters, reasons
    
    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors (0-1 range)"""
        vec1_arr = np.array(vec1)
        vec2_arr = np.array(vec2)
        
        dot_product = np.dot(vec1_arr, vec2_arr)
        norm_product = np.linalg.norm(vec1_arr) * np.linalg.norm(vec2_arr)
        
        if norm_product == 0:
            return 0.0
        
        return float(dot_product / norm_product)