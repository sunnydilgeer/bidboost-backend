from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference
from app.models.contract import Contract
from qdrant_client import QdrantClient
from app.core.config import settings
import numpy as np
import logging

logger = logging.getLogger(__name__)


class ContractMatchScorer:
    """
    Scores contract opportunities against company profiles using:
    - Semantic similarity between capabilities and contract requirements
    - Past win matching (similar buyers, contract values)
    - Search preference filtering (value ranges, regions, keywords)
    - Set-aside certification matching (SDVOSB, WOSB, HUBZone, 8(a), SBA)
    
    Supports both Qdrant (capabilities) and Pinecone (SAM contracts)
    """
    
    def __init__(self, db: Session, qdrant_client: QdrantClient):
        self.db = db
        self.qdrant = qdrant_client
        
        # Initialize Pinecone if enabled
        self.use_pinecone = settings.USE_PINECONE
        if self.use_pinecone:
            from pinecone import Pinecone
            pc = Pinecone(api_key=settings.PINECONE_API_KEY)
            self.pinecone_index = pc.Index(settings.PINECONE_INDEX_NAME)
            logger.info("ContractMatchScorer initialized with Pinecone for SAM contracts")
        else:
            self.pinecone_index = None
            logger.info("ContractMatchScorer initialized with Qdrant only")

    def get_improvement_recommendations(
        self, 
        firm_id: str
    ) -> List[Dict[str, any]]:
        """Generate actionable recommendations to improve match scores."""
        
        # Load company profile with all relationships
        profile = self.db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == firm_id
        ).first()
        
        if not profile:
            logger.warning(f"No profile found for firm {firm_id}")
            return []
        
        recommendations = []
        
        # 1. PAST WINS ANALYSIS (30% weight potential)
        past_wins_count = len(profile.past_wins) if profile.past_wins else 0
        
        if past_wins_count == 0:
            recommendations.append({
                "category": "past_wins",
                "current_score": 0.0,
                "potential_score": 30.0,
                "priority": "high",
                "action": "Add 1-2 similar past federal contract wins to demonstrate relevant experience",
                "impact": "+30% to total match score",
                "icon": "🎯",
                "specific_actions": [
                    "Add a past win in your main capability area",
                    "Include contract value and federal agency name",
                    "Focus on government/federal contracts"
                ]
            })
        elif past_wins_count < 3:
            potential_boost = (3 - past_wins_count) * 10
            recommendations.append({
                "category": "past_wins",
                "current_score": past_wins_count * 10.0,
                "potential_score": 30.0,
                "priority": "medium",
                "action": f"Add {3 - past_wins_count} more past wins to strengthen your track record",
                "impact": f"+{potential_boost}% potential boost",
                "icon": "📈",
                "specific_actions": [
                    "Add wins from different federal agencies",
                    "Include recent contracts (last 2-3 years)",
                    f"Aim for at least 3 past wins for credibility"
                ]
            })
        
        # 2. CAPABILITIES ANALYSIS (40% weight potential)
        capabilities_count = len(profile.capabilities) if profile.capabilities else 0
        
        if capabilities_count < 3:
            recommendations.append({
                "category": "capabilities",
                "current_score": capabilities_count * 10.0,
                "potential_score": 40.0,
                "priority": "high" if capabilities_count < 2 else "medium",
                "action": f"Add {max(3 - capabilities_count, 1)} domain-specific capabilities",
                "impact": f"+{min(15, (3 - capabilities_count) * 5)}% potential boost",
                "icon": "💡",
                "specific_actions": [
                    "Use specific terminology like 'Cybersecurity Compliance (NIST)' instead of 'IT Services'",
                    "Add 'Federal Cloud Migration (FedRAMP)' or 'Defense Systems Integration'",
                    "Match language from SAM.gov contracts you're interested in"
                ]
            })
        elif capabilities_count < 5:
            # Check if capabilities are too generic
            generic_keywords = ["it", "software", "services", "solutions", "general", "consulting"]
            generic_count = 0
            
            for cap in profile.capabilities:
                cap_text_lower = cap.capability_text.lower()
                if any(keyword in cap_text_lower for keyword in generic_keywords):
                    generic_count += 1
            
            if generic_count > capabilities_count / 2:
                recommendations.append({
                    "category": "capabilities",
                    "current_score": capabilities_count * 8.0,
                    "potential_score": 40.0,
                    "priority": "medium",
                    "action": "Make capabilities more specific to improve semantic matching",
                    "impact": "+10-15% better relevance scores",
                    "icon": "🎨",
                    "specific_actions": [
                        "Replace 'IT Services' → 'Cybersecurity Auditing & FISMA Compliance'",
                        "Replace 'Software Development' → 'Agile Development for Federal Agencies'",
                        "Use exact phrases from high-scoring SAM.gov contracts"
                    ]
                })
        
        # 3. SEARCH PREFERENCES ANALYSIS (30% weight optimization)
        prefs = profile.search_preference
        missing_prefs = []
        potential_impact = 0
        
        if not prefs:
            recommendations.append({
                "category": "preferences",
                "current_score": 0.0,
                "potential_score": 30.0,
                "priority": "low",
                "action": "Set search preferences to filter and focus results",
                "impact": "+30% better targeted results",
                "icon": "⚙️",
                "specific_actions": [
                    "Set minimum/maximum contract values",
                    "Add preferred states/regions (e.g., CA, TX, VA, DC)",
                    "Add keywords for your specialization"
                ]
            })
        else:
            if not prefs.min_contract_value and not prefs.max_contract_value:
                missing_prefs.append("contract value range")
                potential_impact += 8
            
            if not prefs.preferred_regions or len(prefs.preferred_regions) == 0:
                missing_prefs.append("preferred regions")
                potential_impact += 10
            
            if not prefs.keywords or len(prefs.keywords) == 0:
                missing_prefs.append("target keywords")
                potential_impact += 7
            
            if missing_prefs:
                recommendations.append({
                    "category": "preferences",
                    "current_score": 30.0 - potential_impact,
                    "potential_score": 30.0,
                    "priority": "low",
                    "action": f"Complete your search preferences: {', '.join(missing_prefs)}",
                    "impact": f"+{potential_impact}% optimization",
                    "icon": "🎯",
                    "specific_actions": [f"Add {pref}" for pref in missing_prefs]
                })
        
        # 4. CERTIFICATION RECOMMENDATIONS (15% boost per matching set-aside)
        cert_recommendations = []
        
        if not profile.sba_certified:
            cert_recommendations.append("SBA Small Business certification")
        if not profile.sdvosb_certified:
            cert_recommendations.append("SDVOSB (Service-Disabled Veteran-Owned)")
        if not profile.wosb_certified:
            cert_recommendations.append("WOSB (Women-Owned Small Business)")
        if not profile.hubzone_certified:
            cert_recommendations.append("HUBZone certification")
        if not profile.eight_a_certified:
            cert_recommendations.append("8(a) Business Development certification")
        
        if cert_recommendations:
            recommendations.append({
                "category": "certifications",
                "current_score": 0.0,
                "potential_score": 15.0,
                "priority": "medium",
                "action": "Consider obtaining relevant federal certifications",
                "impact": "+15% boost for each matching set-aside contract",
                "icon": "🏅",
                "specific_actions": cert_recommendations[:3]  # Show top 3
            })
        
        # Sort by priority: high → medium → low
        priority_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(key=lambda x: priority_order[x["priority"]])
        
        logger.info(f"Generated {len(recommendations)} recommendations for firm {firm_id}")
        return recommendations
    
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
        
        # 3. Search Preference Filtering + Certification Matching (30% weight)
        preference_score, passes_filters, pref_reasons = self._calculate_preference_score(
            contract, profile, profile.search_preference
        )
        scores["preference_score"] = preference_score
        scores["match_reasons"].extend(pref_reasons)
        
        # Don't return contracts that fail hard filters
        if not passes_filters:
            logger.debug(f"Contract {contract.notice_id} failed preference filters")
            return None
        
        # Calculate weighted total score
        scores["total_score"] = (
            capability_score * 0.5 +
            past_win_score * 0.25 +
            preference_score * 0.25
        )
        
        logger.info(f"Contract {contract.notice_id} scored {scores['total_score']:.2%} for firm {firm_id}")
        
        return scores
    
    def _calculate_capability_score(
        self, 
        contract: Contract, 
        capabilities: List[CompanyCapability]
    ) -> float:
        """Use semantic similarity between capabilities and contract description"""
        if not capabilities:
            logger.debug(f"No capabilities found")
            return 0.0
        
        try:
            from app.services.capability_store_pinecone import get_capability_store
            
            # Get contract embedding from Pinecone
            contract_vector = None
            
            if contract.qdrant_id:
                try:
                    # SAM contracts are in Pinecone (default namespace)
                    result = self.pinecone_index.fetch(ids=[contract.qdrant_id], namespace="contracts")
                    if contract.qdrant_id in result.vectors:
                        contract_vector = result.vectors[contract.qdrant_id].values
                        logger.debug(f"Retrieved SAM contract vector from Pinecone: {contract.qdrant_id}")
                except Exception as e:
                    logger.error(f"Failed to fetch contract from Pinecone: {e}")
            
            if not contract_vector:
                logger.warning(f"Contract {contract.qdrant_id} vector not found in Pinecone")
                return 0.0
            
            # Get capabilities from Pinecone (capabilities namespace)
            cap_store = get_capability_store()
            
            # Batch fetch all capabilities
            capability_ids = [cap.qdrant_id for cap in capabilities if cap.qdrant_id]
            
            if not capability_ids:
                logger.warning("No capabilities have Pinecone IDs")
                return 0.0
            
            capabilities_data = cap_store.get_capabilities_batch(capability_ids)
            
            # Calculate similarity with each capability
            similarities = []
            for cap in capabilities:
                if cap.qdrant_id and cap.qdrant_id in capabilities_data:
                    cap_data = capabilities_data[cap.qdrant_id]
                    cap_vector = cap_data["vector"]
                    
                    similarity = self._cosine_similarity(contract_vector, cap_vector)
                    similarities.append(similarity)
                    logger.debug(f"Capability '{cap.capability_text[:50]}' similarity: {similarity:.3f}")
            
            if not similarities:
                logger.warning("No similarities calculated")
                return 0.0
            
            # Use average of top 3 matches
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
                        reasons.append(f"Similar contract value to past win (${win.contract_value:,.0f})")
        
        # Cap score at 1.0
        final_score = min(score, 1.0)
        
        return final_score, reasons
    
    def _calculate_preference_score(
        self, 
        contract: Contract,
        profile: CompanyProfile,
        preferences: Optional[SearchPreference]
    ) -> tuple[float, bool, List[str]]:
        """
        Apply search preferences and certification matching as filters and scoring.
        
        Returns:
            - score (float): Preference match score 0-1.5 (allows for bonuses)
            - passes_filters (bool): Whether contract passes hard filters
            - reasons (List[str]): Match reasons for display
        """
        passes_filters = True
        score = 1.0
        reasons = []
        
        # ===== SET-ASIDE CERTIFICATION MATCHING (15% BONUS) =====
        if hasattr(contract, 'set_aside') and contract.set_aside:
            set_aside_lower = contract.set_aside.lower()
            
            # Check each certification type and award 15% bonus for matches
            if profile.sba_certified and any(kw in set_aside_lower for kw in ['small business', 'sba', 'total small business']):
                score += 0.15
                reasons.append("✓ Matches your Small Business certification")
            
            if profile.sdvosb_certified and ('sdvosb' in set_aside_lower or 'service-disabled' in set_aside_lower):
                score += 0.15
                reasons.append("✓ Matches your SDVOSB certification")
            
            if profile.wosb_certified and ('wosb' in set_aside_lower or 'women-owned' in set_aside_lower):
                score += 0.15
                reasons.append("✓ Matches your WOSB certification")
            
            if profile.hubzone_certified and 'hubzone' in set_aside_lower:
                score += 0.15
                reasons.append("✓ Matches your HUBZone certification")
            
            if profile.eight_a_certified and ('8(a)' in set_aside_lower or '8a' in set_aside_lower):
                score += 0.15
                reasons.append("✓ Matches your 8(a) certification")
        
        # ===== EXISTING PREFERENCE FILTERS BELOW =====
        
        if not preferences:
            return score, True, reasons  # No preferences = pass all with certification bonus
        
        # Value range filter (HARD)
        if contract.contract_value:
            if preferences.min_contract_value and contract.contract_value < preferences.min_contract_value:
                passes_filters = False
                logger.debug(f"Contract value ${contract.contract_value:,.0f} below minimum ${preferences.min_contract_value:,.0f}")
            
            if preferences.max_contract_value and contract.contract_value > preferences.max_contract_value:
                passes_filters = False
                logger.debug(f"Contract value ${contract.contract_value:,.0f} above maximum ${preferences.max_contract_value:,.0f}")
            
            # Add reason if value is in range
            if passes_filters and (preferences.min_contract_value or preferences.max_contract_value):
                reasons.append(f"Contract value (${contract.contract_value:,.0f}) matches preferences")
        
        # Excluded categories filter (HARD)
        if preferences.excluded_categories:
            contract_text = f"{contract.title} {contract.description or ''}".lower()
            for category in preferences.excluded_categories:
                category_lower = category.lower()
                if category_lower in contract_text:
                    passes_filters = False
                    logger.debug(f"Contract contains excluded category: {category}")
                    break
        
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
        
        # Cap final score at 1.5 (to allow for certification and keyword bonuses)
        final_score = min(score, 1.5)
        
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