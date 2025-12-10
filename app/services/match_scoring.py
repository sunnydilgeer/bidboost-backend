import logging
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference
from app.models.contract import Contract
import numpy as np

logger = logging.getLogger(__name__)

class ContractMatchScorer:
    """
    Calculate personalized match scores for contracts based on:
    - Capability similarity (semantic matching)
    - Past win patterns (agency/value matching)
    - Search preferences (filters and keywords)
    """
    
    def __init__(self, db: Session, vector_client):
        self.db = db
        
        # Auto-detect client type (Pinecone or Qdrant)
        if hasattr(vector_client, 'fetch'):  # Pinecone Index
            self.pinecone_index = vector_client
            self.qdrant_client = None
            self.using_pinecone = True
            logger.info("ContractMatchScorer initialized with Pinecone")
        else:  # Qdrant Client
            self.qdrant_client = vector_client
            self.pinecone_index = None
            self.using_pinecone = False
            logger.info("ContractMatchScorer initialized with Qdrant")
    
    def score_contract(
        self, 
        contract: Contract, 
        firm_id: str, 
        capability_vectors: Optional[Dict] = None,
        contract_vectors: Optional[Dict] = None,
        past_win_vectors: Optional[Dict[str, List[float]]] = None  # ✅ ADD THIS

    ) -> Optional[Dict]:
        """
        Calculate comprehensive match score for a contract.
        
        Args:
            contract: Contract to score
            firm_id: Company identifier
            capability_vectors: Pre-fetched capability vectors {capability_id: vector}
            contract_vectors: Pre-fetched contract vectors {contract_id: vector}
        
        Returns:
            Dict with scores and reasons, or None if filtered out
        """
        try:
            # Get company profile
            profile = self.db.query(CompanyProfile).filter(
                CompanyProfile.firm_id == firm_id
            ).first()
            
            if not profile:
                logger.warning(f"No profile found for firm {firm_id}")
                return None
            
            # Apply preference filters first (quick elimination)
            if not self._passes_preference_filters(contract, profile):
                return None
            
            # Calculate component scores
            capability_score = self._calculate_capability_score(
                contract, 
                profile,
                capability_vectors,
                contract_vectors  # NEW: Pass pre-fetched contract vectors
            )
            past_win_score = self._calculate_past_win_score(contract, profile, past_win_vectors)

            preference_score = self._calculate_preference_score(contract, profile)
            
            # Weighted average: Capability (50%), Past Wins (25%), Preferences (25%)
            total_score = (
                capability_score * 0.5 +
                past_win_score * 0.25 +
                preference_score * 0.25
            )
            
            # Generate match reasons
            match_reasons = self._generate_match_reasons(
                capability_score, 
                past_win_score, 
                preference_score,
                contract,
                profile
            )
            
            return {
                "total_score": round(total_score, 2),
                "capability_score": round(capability_score, 2),
                "past_win_score": round(past_win_score, 2),
                "preference_score": round(preference_score, 2),
                "match_reasons": match_reasons
            }
            
        except Exception as e:
            logger.error(f"Error scoring contract {contract.notice_id}: {str(e)}", exc_info=True)
            return None
    
    def _calculate_capability_score(
        self, 
        contract: Contract, 
        profile: CompanyProfile,
        capability_vectors: Optional[Dict] = None,
        contract_vectors: Optional[Dict] = None  # NEW: Pre-fetched contract vectors
    ) -> float:
        """
        Calculate semantic similarity between contract and company capabilities.
        Uses pre-fetched vectors when available for performance.
        """
        try:
            capabilities = profile.capabilities
            
            if not capabilities:
                logger.debug(f"No capabilities for firm {profile.firm_id}")
                return 0.0
            
            # Get contract vector (use pre-fetched if available)
            contract_vector = None
            
            if contract_vectors is not None and contract.qdrant_id in contract_vectors:
                # Use pre-fetched contract vector
                contract_vector = contract_vectors[contract.qdrant_id]
                logger.debug(f"Using pre-fetched contract vector: {contract.qdrant_id}")
            elif contract.qdrant_id:
                # Fallback: Fetch individually
                if self.using_pinecone:
                    result = self.pinecone_index.fetch(ids=[contract.qdrant_id], namespace="contracts")
                    if result.vectors and contract.qdrant_id in result.vectors:
                        contract_vector = result.vectors[contract.qdrant_id].values
                        logger.debug(f"Fetched contract vector individually: {contract.qdrant_id}")
                else:
                    # Qdrant fallback
                    points = self.qdrant_client.retrieve(
                        collection_name="legal_documents",
                        ids=[contract.qdrant_id],
                        with_vectors=True
                    )
                    if points:
                        contract_vector = points[0].vector
                        logger.debug(f"Fetched contract vector from Qdrant: {contract.qdrant_id}")
            
            if contract_vector is None:
                logger.warning(f"No vector found for contract {contract.qdrant_id}")
                return 0.0
            
            # Get capability vectors (use pre-fetched if available)
            # FIXED: Check if capability_vectors is not None instead of truthiness
            if capability_vectors is not None:
                capabilities_data = capability_vectors
                logger.debug(f"Using pre-fetched capability vectors: {len(capabilities_data)} capabilities")
            else:
                # Fallback: Fetch capabilities individually
                capability_ids = [cap.qdrant_id for cap in capabilities if cap.qdrant_id]
                
                if not capability_ids:
                    logger.warning(f"No capability IDs found for firm {profile.firm_id}")
                    return 0.0
                
                if self.using_pinecone:
                    from app.services.capability_store_pinecone import get_capability_store
                    cap_store = get_capability_store()
                    capabilities_data = cap_store.get_capabilities_batch(capability_ids)
                    logger.debug(f"Fetched {len(capabilities_data)} capabilities from Pinecone")
                else:
                    # Qdrant fallback
                    points = self.qdrant_client.retrieve(
                        collection_name="capabilities",
                        ids=capability_ids,
                        with_vectors=True
                    )
                    capabilities_data = {p.id: p.vector for p in points}
                    logger.debug(f"Fetched {len(capabilities_data)} capabilities from Qdrant")
            
            if not capabilities_data:
                logger.warning(f"No capability vectors retrieved for firm {profile.firm_id}")
                return 0.0
            
            # Calculate similarities
            similarities = []
            for cap in capabilities:
                if cap.qdrant_id in capabilities_data:
                    cap_vector = capabilities_data[cap.qdrant_id]
                    similarity = self._cosine_similarity(contract_vector, cap_vector)
                    similarities.append(similarity)
            
            if not similarities:
                logger.warning(f"No similarity scores calculated for contract {contract.notice_id}")
                return 0.0
            
            # Average similarity across all capabilities
            avg_similarity = float(np.mean(similarities))
            
            logger.debug(f"Capability score: {avg_similarity:.3f} (from {len(similarities)} capabilities)")
            
            return avg_similarity
            
        except Exception as e:
            logger.error(f"Error calculating capability score: {str(e)}", exc_info=True)
            return 0.0
    
    
    # ========== UPDATED _calculate_past_win_score METHOD ==========
# In app/services/match_scoring.py
# Replace the entire _calculate_past_win_score method (around lines 195-320) with this:

    def _calculate_past_win_score(
        self, 
        contract: Contract, 
        profile: CompanyProfile,
        past_win_vectors: Optional[Dict[str, List[float]]] = None
    ) -> float:
        """
        Calculate semantic similarity between contract and past wins.
        Uses Pinecone embeddings for accurate matching instead of keywords.
        
        Args:
            contract: Contract to score
            profile: CompanyProfile with past_wins relationship
            past_win_vectors: Optional pre-fetched vectors {pinecone_id: vector}
        
        Returns:
            Score from 0.0 to 1.0 representing best past win match
        """
        try:
            past_wins = profile.past_wins
            
            if not past_wins:
                logger.debug(f"No past wins for firm {profile.firm_id}")
                return 0.0
            
            # Get contract vector (use pre-fetched if available)
            contract_vector = None
            
            if contract.qdrant_id:
                if self.using_pinecone:
                    result = self.pinecone_index.fetch(ids=[contract.qdrant_id], namespace="contracts")
                    if result.vectors and contract.qdrant_id in result.vectors:
                        contract_vector = list(result.vectors[contract.qdrant_id].values)
                        logger.debug(f"Fetched contract vector for past win scoring: {contract.qdrant_id}")
                else:
                    # Qdrant fallback
                    points = self.qdrant_client.retrieve(
                        collection_name="legal_documents",
                        ids=[contract.qdrant_id],
                        with_vectors=True
                    )
                    if points:
                        contract_vector = points[0].vector
            
            if contract_vector is None:
                logger.warning(f"No contract vector found for past win scoring: {contract.qdrant_id}")
                return 0.0
            
            # Get past win vectors (use pre-fetched if available)
            if past_win_vectors is not None:
                wins_data = past_win_vectors
                logger.debug(f"Using pre-fetched past win vectors: {len(wins_data)} wins")
            else:
                # Fallback: Fetch past wins individually
                pinecone_ids = [win.pinecone_id for win in past_wins if win.pinecone_id]
                
                if not pinecone_ids:
                    logger.warning(f"No pinecone_ids found for past wins (firm {profile.firm_id})")
                    return 0.0
                
                if self.using_pinecone:
                    from app.services.past_win_store_pinecone import get_past_win_store
                    win_store = get_past_win_store()
                    wins_data = win_store.get_past_wins_batch(pinecone_ids)
                    logger.debug(f"Fetched {len(wins_data)} past win vectors from Pinecone")
                else:
                    # Qdrant fallback (if you have past wins in Qdrant)
                    wins_data = {}
                    logger.warning("Qdrant fallback not implemented for past wins")
            
            if not wins_data:
                logger.warning(f"No past win vectors retrieved for firm {profile.firm_id}")
                return 0.0
            
            # Calculate similarities with each past win
            similarities = []
            for win in past_wins:
                if win.pinecone_id and win.pinecone_id in wins_data:
                    win_vector = wins_data[win.pinecone_id]
                    
                    # Cosine similarity
                    similarity = self._cosine_similarity(contract_vector, win_vector)
                    similarities.append(similarity)
                    
                    if similarity > 0.6:  # Log high matches
                        logger.debug(f"Strong past win match: '{win.contract_title[:50]}...' -> {similarity:.2%}")
            
            if not similarities:
                logger.warning(f"No similarity scores calculated for contract {contract.notice_id}")
                return 0.0
            
            # Return best match (highest similarity)
            best_match = max(similarities)
            
            logger.debug(f"Past win score: {best_match:.3f} (from {len(similarities)} past wins)")
            
            return float(best_match)
            
        except Exception as e:
            logger.error(f"Error calculating past win score: {str(e)}", exc_info=True)
            return 0.0
    
    def _calculate_preference_score(self, contract: Contract, profile: CompanyProfile) -> float:
        """
        Score based on how well contract matches search preferences.
        Higher score for preferred regions and keyword matches.
        """
        try:
            prefs = profile.search_preference
            
            if not prefs:
                return 0.5  # Neutral if no preferences set
            
            score = 0.5  # Start neutral
            
            # Region preference
            if prefs.preferred_regions and contract.region:
                if contract.region in prefs.preferred_regions:
                    score += 0.3
            
            # Keyword matches in title/description
            if prefs.keywords:
                text = f"{contract.title} {contract.description}".lower()
                matched_keywords = [kw for kw in prefs.keywords if kw.lower() in text]
                
                if matched_keywords:
                    score += 0.2 * (len(matched_keywords) / len(prefs.keywords))
            
            return min(score, 1.0)
            
        except Exception as e:
            logger.error(f"Error calculating preference score: {str(e)}")
            return 0.5
    
    def _passes_preference_filters(self, contract: Contract, profile: CompanyProfile) -> bool:
        """
        Apply hard filters based on search preferences.
        Returns False if contract should be excluded.
        """
        try:
            prefs = profile.search_preference
            
            if not prefs:
                return True  # No filters set
            
            # Value range filters
            if contract.contract_value:
                if prefs.min_contract_value and contract.contract_value < prefs.min_contract_value:
                    return False
                if prefs.max_contract_value and contract.contract_value > prefs.max_contract_value:
                    return False
            
            # Excluded categories (if implemented)
            # This would need category field on contracts
            
            return True
            
        except Exception as e:
            logger.error(f"Error applying preference filters: {str(e)}")
            return True  # On error, don't filter out
    
    def _generate_match_reasons(
        self, 
        capability_score: float,
        past_win_score: float,
        preference_score: float,
        contract: Contract,
        profile: CompanyProfile
    ) -> List[str]:
        """Generate human-readable reasons for the match score."""
        reasons = []
        
        try:
            # Capability matches
            if capability_score > 0.7:
                reasons.append("Strong capability match - your expertise aligns well with this contract")
            elif capability_score > 0.5:
                reasons.append("Good capability match - relevant to your services")
            
            # Past win patterns
            if past_win_score > 0.7:
                past_wins = profile.past_wins
                matching_agency = any(
                    win.buyer_name and contract.buyer_name and 
                    win.buyer_name.lower() in contract.buyer_name.lower()
                    for win in past_wins
                )
                
                if matching_agency:
                    reasons.append(f"You've won contracts from {contract.buyer_name} before")
                else:
                    reasons.append("Contract value matches your past wins")
            elif past_win_score > 0.4:
                reasons.append("Similar to your past contract wins")
            
            # Preference matches
            if preference_score > 0.7 and profile.search_preference:
                prefs = profile.search_preference
                
                if prefs.preferred_regions and contract.region in prefs.preferred_regions:
                    reasons.append(f"In your preferred region: {contract.region}")
                
                if prefs.keywords:
                    text = f"{contract.title} {contract.description}".lower()
                    matched = [kw for kw in prefs.keywords if kw.lower() in text]
                    if matched:
                        reasons.append(f"Matches keywords: {', '.join(matched[:3])}")
            
            # Default reason if no specific matches
            if not reasons:
                reasons.append("Relevant to your profile")
            
            return reasons
            
        except Exception as e:
            logger.error(f"Error generating match reasons: {str(e)}")
            return ["Match based on profile analysis"]
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        try:
            vec1_np = np.array(vec1)
            vec2_np = np.array(vec2)
            
            dot_product = np.dot(vec1_np, vec2_np)
            norm1 = np.linalg.norm(vec1_np)
            norm2 = np.linalg.norm(vec2_np)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            return float(dot_product / (norm1 * norm2))
            
        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {str(e)}")
            return 0.0
    
    def get_improvement_recommendations(self, firm_id: str) -> List[Dict]:
        """
        Analyze profile and suggest improvements to increase match scores.
        
        Returns list of recommendations with:
        - category: What to improve
        - priority: high/medium/low
        - message: What action to take
        - impact: Expected score improvement
        """
        try:
            profile = self.db.query(CompanyProfile).filter(
                CompanyProfile.firm_id == firm_id
            ).first()
            
            if not profile:
                return []
            
            recommendations = []
            
            # Check capabilities
            capabilities_count = len(profile.capabilities) if profile.capabilities else 0
            
            if capabilities_count == 0:
                recommendations.append({
                    "category": "capabilities",
                    "priority": "high",
                    "message": "Add capabilities to start getting personalized matches",
                    "impact": "Enables capability scoring (50% of match score)"
                })
            elif capabilities_count < 3:
                recommendations.append({
                    "category": "capabilities",
                    "priority": "medium",
                    "message": f"Add {3 - capabilities_count} more capabilities for better matches",
                    "impact": "Improves capability coverage and matching accuracy"
                })
            
            # Check past wins
            past_wins_count = len(profile.past_wins) if profile.past_wins else 0
            
            if past_wins_count == 0:
                recommendations.append({
                    "category": "past_wins",
                    "priority": "medium",
                    "message": "Add past contract wins to improve agency and value matching",
                    "impact": "Enhances past win scoring (25% of match score)"
                })
            elif past_wins_count < 3:
                recommendations.append({
                    "category": "past_wins",
                    "priority": "low",
                    "message": "Add more past wins to identify patterns in your successful contracts",
                    "impact": "Better prediction of suitable opportunities"
                })
            
            # Check preferences
            if not profile.search_preference:
                recommendations.append({
                    "category": "preferences",
                    "priority": "medium",
                    "message": "Set search preferences to filter out irrelevant contracts",
                    "impact": "Reduces noise and focuses on relevant opportunities"
                })
            else:
                prefs = profile.search_preference
                
                if not prefs.preferred_regions:
                    recommendations.append({
                        "category": "preferences",
                        "priority": "low",
                        "message": "Add preferred regions to prioritize local opportunities",
                        "impact": "Improves preference scoring (25% of match score)"
                    })
                
                if not prefs.keywords:
                    recommendations.append({
                        "category": "preferences",
                        "priority": "low",
                        "message": "Add keywords to highlight contracts with specific terms",
                        "impact": "Better filtering and relevance scoring"
                    })
            
            # Sort by priority
            priority_order = {"high": 0, "medium": 1, "low": 2}
            recommendations.sort(key=lambda x: priority_order.get(x["priority"], 3))
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error generating recommendations: {str(e)}", exc_info=True)
            return []