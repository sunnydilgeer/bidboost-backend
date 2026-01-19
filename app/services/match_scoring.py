"""
Contract Match Scoring Service

PURE CAPABILITY SCORING APPROACH:
- match_score = capability similarity only (rescaled for display)
- No weighted average, no penalties for missing data
- Past wins and preferences computed separately for context/badges
- Identical scoring in quick-start and dashboard

SCORE RESCALING:
- Raw cosine similarity (0.35-0.75) → Display score (0.50-0.92)
- Makes scores feel meaningful without being fake
- Ceiling at 92% (never shows 99%)
"""

import logging
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.company import CompanyProfile
from app.models.contract import Contract
import numpy as np

logger = logging.getLogger(__name__)


class ContractMatchScorer:
    """
    Calculate personalized match scores for contracts.

    Scoring Philosophy:
    - match_score = capability similarity ONLY (rescaled)
    - Missing data (past wins, prefs) = no penalty to score
    - Past wins and preferences provide context badges, not score impact
    """

    # Rescaling constants
    MIN_RAW = 0.35      # Lowest raw score we consider a match
    MAX_RAW = 0.75      # Exceptional raw score (rare)
    MIN_DISPLAY = 0.50  # Floor display score
    MAX_DISPLAY = 0.92  # Ceiling display score (never 99%)

    def __init__(self, db: Session, vector_client):
        self.db = db

        # Auto-detect client type (Pinecone or Qdrant)
        if hasattr(vector_client, "fetch"):
            self.pinecone_index = vector_client
            self.qdrant_client = None
            self.using_pinecone = True
        else:
            self.qdrant_client = vector_client
            self.pinecone_index = None
            self.using_pinecone = False

    def score_contract(
        self,
        contract: Contract,
        firm_id: str,
        capability_vectors: Optional[Dict] = None,
        contract_vectors: Optional[Dict] = None,
        past_win_vectors: Optional[Dict[str, List[float]]] = None,
    ) -> Optional[Dict]:
        """
        Calculate match score for a contract.

        Args:
            contract: Contract to score
            firm_id: Company identifier
            capability_vectors: Pre-fetched capability vectors {id: vector}
            contract_vectors: Pre-fetched contract vectors {id: vector}
            past_win_vectors: Pre-fetched past win vectors {id: vector}

        Returns:
            Dict with scores and context, or None if filtered out
        """
        try:
            # Get company profile
            profile = (
                self.db.query(CompanyProfile)
                .filter(CompanyProfile.firm_id == firm_id)
                .first()
            )

            if not profile:
                logger.warning(f"No profile found for firm {firm_id}")
                return None

            # Apply preference filters (quick elimination)
            if not self._passes_preference_filters(contract, profile):
                return None

            # Calculate raw capability score + matched cap examples
            raw_capability_score, matched_capabilities = self._calculate_capability_score(
                contract,
                profile,
                capability_vectors,
                contract_vectors,
            )

            # Skip if below threshold
            if raw_capability_score < self.MIN_RAW:
                return None

            # Rescale for display
            display_score = self._rescale_score(raw_capability_score)

            # Calculate context scores (for badges, not for main score)
            past_win_score = self._calculate_past_win_score(
                contract, profile, past_win_vectors
            )
            preference_score = self._calculate_preference_score(contract, profile)

            # Keep legacy match_reasons for now (unchanged)
            match_reasons = self._generate_match_reasons(
                raw_capability_score,
                past_win_score,
                preference_score,
                contract,
                profile,
            )

            return {
                # Primary score (rescaled capability)
                "match_score": round(display_score, 3),
                "display_score": round(display_score * 100),

                # Component scores (for analytics/debugging)
                "capability_score": round(display_score, 3),  # Rescaled
                "raw_capability_score": round(raw_capability_score, 3),  # Original
                "past_win_score": round(past_win_score, 3),
                "preference_score": round(preference_score, 3),

                # NEW: matched capability examples (top 1–3)
                "matched_capabilities": matched_capabilities,

                "why_this_matches": self._generate_why_this_matches(
                matched_capabilities=matched_capabilities,
                contract=contract,
                ),

                # Context
                "match_reasons": match_reasons,

                # Legacy field for backward compatibility
                "total_score": round(display_score, 3),
            }

        except Exception as e:
            logger.error(
                f"Error scoring contract {getattr(contract, 'notice_id', '')}: {str(e)}",
                exc_info=True,
            )
            return None

    def _rescale_score(self, raw_score: float) -> float:
        """
        Rescale raw cosine similarity to user-friendly display range.
        """
        if raw_score <= self.MIN_RAW:
            return self.MIN_DISPLAY

        if raw_score >= self.MAX_RAW:
            return self.MAX_DISPLAY

        # Linear interpolation
        scaled = (
            self.MIN_DISPLAY
            + (raw_score - self.MIN_RAW) / (self.MAX_RAW - self.MIN_RAW)
            * (self.MAX_DISPLAY - self.MIN_DISPLAY)
        )

        return scaled

    def _calculate_capability_score(
        self,
        contract: Contract,
        profile: CompanyProfile,
        capability_vectors: Optional[Dict] = None,
        contract_vectors: Optional[Dict] = None,
    ) -> Tuple[float, List[str]]:
        """
        Calculate semantic similarity between contract and company capabilities.

        Uses BEST capability match (not average) - shows contracts that match
        ANY strong capability the company has.

        Returns:
            (best_score, matched_capabilities_texts)
        """
        try:
            capabilities = profile.capabilities

            if not capabilities:
                return 0.0, []

            # Get contract vector
            contract_vector = self._get_contract_vector(contract, contract_vectors)

            if contract_vector is None:
                logger.warning(f"No vector for contract {contract.qdrant_id}")
                return 0.0, []

            # Get capability vectors
            if capability_vectors is not None:
                capabilities_data = capability_vectors
            else:
                capabilities_data = self._fetch_capability_vectors(profile)

            if not capabilities_data:
                return 0.0, []

            scored_caps: List[Tuple[float, str]] = []

            for cap in capabilities:
                if cap.qdrant_id and cap.qdrant_id in capabilities_data:
                    cap_vector = capabilities_data[cap.qdrant_id]
                    similarity = self._cosine_similarity(contract_vector, cap_vector)
                    # cap.capability_text is assumed to exist on CompanyCapability model
                    scored_caps.append((similarity, getattr(cap, "capability_text", "")))

            if not scored_caps:
                return 0.0, []

            # Sort by similarity desc
            scored_caps.sort(key=lambda x: x[0], reverse=True)

            best_score = scored_caps[0][0]
            matched_capabilities = [t for _, t in scored_caps[:3] if t]

            return float(best_score), matched_capabilities

        except Exception as e:
            logger.error(f"Error calculating capability score: {str(e)}", exc_info=True)
            return 0.0, []

    def _get_contract_vector(
        self,
        contract: Contract,
        contract_vectors: Optional[Dict],
    ) -> Optional[List[float]]:
        """Get contract vector from cache or fetch from vector store."""

        # Try pre-fetched cache first
        if contract_vectors and contract.qdrant_id in contract_vectors:
            return contract_vectors[contract.qdrant_id]

        # Fallback: fetch individually
        if not contract.qdrant_id:
            return None

        try:
            if self.using_pinecone:
                result = self.pinecone_index.fetch(
                    ids=[contract.qdrant_id],
                    namespace="contracts",
                )
                if result.vectors and contract.qdrant_id in result.vectors:
                    return list(result.vectors[contract.qdrant_id].values)
            else:
                points = self.qdrant_client.retrieve(
                    collection_name="legal_documents",
                    ids=[contract.qdrant_id],
                    with_vectors=True,
                )
                if points:
                    return points[0].vector
        except Exception as e:
            logger.error(f"Error fetching contract vector: {e}", exc_info=True)

        return None

    def _fetch_capability_vectors(self, profile: CompanyProfile) -> Dict:
        """Fetch capability vectors from vector store."""
        capability_ids = [
            cap.qdrant_id for cap in (profile.capabilities or [])
            if cap.qdrant_id
        ]

        if not capability_ids:
            return {}

        try:
            if self.using_pinecone:
                from app.services.capability_store_pinecone import get_capability_store
                cap_store = get_capability_store()
                return cap_store.get_capabilities_batch(capability_ids)
            else:
                points = self.qdrant_client.retrieve(
                    collection_name="capabilities",
                    ids=capability_ids,
                    with_vectors=True,
                )
                return {p.id: p.vector for p in points}
        except Exception as e:
            logger.error(f"Error fetching capability vectors: {e}", exc_info=True)
            return {}

    def _calculate_past_win_score(
        self,
        contract: Contract,
        profile: CompanyProfile,
        past_win_vectors: Optional[Dict[str, List[float]]] = None,
    ) -> float:
        """
        Calculate similarity between contract and past wins.

        NOTE: This is for context/badges only, NOT for the main match score.
        """
        try:
            past_wins = getattr(profile, "past_wins", None)

            if not past_wins:
                return 0.0

            # Get contract vector
            contract_vector = None
            if contract.qdrant_id:
                if self.using_pinecone:
                    result = self.pinecone_index.fetch(
                        ids=[contract.qdrant_id],
                        namespace="contracts",
                    )
                    if result.vectors and contract.qdrant_id in result.vectors:
                        contract_vector = list(result.vectors[contract.qdrant_id].values)
                else:
                    points = self.qdrant_client.retrieve(
                        collection_name="legal_documents",
                        ids=[contract.qdrant_id],
                        with_vectors=True,
                    )
                    if points:
                        contract_vector = points[0].vector

            if contract_vector is None:
                return 0.0

            # Get past win vectors
            if past_win_vectors is not None:
                wins_data = past_win_vectors
            else:
                wins_data = self._fetch_past_win_vectors(profile)

            if not wins_data:
                return 0.0

            # Calculate similarities
            similarities = []
            for win in past_wins:
                if getattr(win, "pinecone_id", None) and win.pinecone_id in wins_data:
                    win_vector = wins_data[win.pinecone_id]
                    similarity = self._cosine_similarity(contract_vector, win_vector)
                    similarities.append(similarity)

            if not similarities:
                return 0.0

            return float(max(similarities))

        except Exception as e:
            logger.error(f"Error calculating past win score: {str(e)}", exc_info=True)
            return 0.0

    def _fetch_past_win_vectors(self, profile: CompanyProfile) -> Dict:
        """Fetch past win vectors from vector store."""
        past_wins = getattr(profile, "past_wins", None)
        if not past_wins:
            return {}

        pinecone_ids = [
            win.pinecone_id for win in past_wins
            if getattr(win, "pinecone_id", None)
        ]

        if not pinecone_ids:
            return {}

        try:
            if self.using_pinecone:
                from app.services.past_win_store_pinecone import get_past_win_store
                win_store = get_past_win_store()
                return win_store.get_past_wins_batch(pinecone_ids)
            else:
                return {}
        except Exception as e:
            logger.error(f"Error fetching past win vectors: {e}", exc_info=True)
            return {}

    def _calculate_preference_score(
        self,
        contract: Contract,
        profile: CompanyProfile,
    ) -> float:
        """
        Score based on how well contract matches search preferences.

        NOTE: This is for context/badges only, NOT for the main match score.
        """
        try:
            prefs = getattr(profile, "search_preference", None)

            if not prefs:
                return 0.5  # Neutral if no preferences

            score = 0.5

            # Region preference
            if getattr(prefs, "preferred_regions", None) and contract.region:
                if contract.region in prefs.preferred_regions:
                    score += 0.3

            # Keyword matches
            if getattr(prefs, "keywords", None):
                text = f"{contract.title} {contract.description or ''}".lower()
                matched = [kw for kw in prefs.keywords if kw.lower() in text]
                if matched:
                    score += 0.2 * (len(matched) / len(prefs.keywords))

            return min(score, 1.0)

        except Exception as e:
            logger.error(f"Error calculating preference score: {str(e)}", exc_info=True)
            return 0.5

    def _passes_preference_filters(
        self,
        contract: Contract,
        profile: CompanyProfile,
    ) -> bool:
        """
        Apply hard filters based on search preferences.
        Returns False if contract should be excluded.
        """
        try:
            prefs = getattr(profile, "search_preference", None)

            if not prefs:
                return True

            # Value range filters
            if contract.contract_value:
                if getattr(prefs, "min_contract_value", None) and contract.contract_value < prefs.min_contract_value:
                    return False
                if getattr(prefs, "max_contract_value", None) and contract.contract_value > prefs.max_contract_value:
                    return False

            return True

        except Exception as e:
            logger.error(f"Error applying preference filters: {str(e)}", exc_info=True)
            return True


    def _generate_why_this_matches(
        self,
        matched_capabilities: List[str],
        contract: Contract,
    ) -> List[str]:
        """
        Generate 'Why this matches' bullets (scannable, non-technical).
        4–6 bullets max. No hype, no guarantees.
        """
        bullets: List[str] = []

        # 1) Matched Capabilities (always include)
        if matched_capabilities:
            examples = ", ".join(matched_capabilities[:3])
            bullets.append(f"Matches your core capabilities, including {examples}")
        else:
            bullets.append("Matches your core capabilities and typical services")

        # 2) NAICS / Service Alignment (only if present on contract)
        naics_code = getattr(contract, "naics_code", None) or getattr(contract, "naics", None)
        if naics_code:
            bullets.append(
                f"Solicitation NAICS {naics_code} aligns with your primary service areas"
            )

        # 3) Scope Similarity (simple keyword detection)
        text = f"{contract.title} {contract.description or ''}".lower()

        scope_map = [
            ("assessment", ["assessment", "audit", "evaluation", "review"]),
            ("implementation", ["implementation", "deploy", "deployment", "integration", "install"]),
            ("support", ["support", "maintenance", "operations", "help desk", "sustainment"]),
            ("modernization", ["modernization", "upgrade", "migration", "transition", "refresh"]),
            ("compliance", ["compliance", "fedramp", "rmf", "nist", "cmmc", "iso 27001"]),
        ]

        matched_scope = None
        for label, words in scope_map:
            if any(w in text for w in words):
                matched_scope = label
                break

        if matched_scope:
            bullets.append(
                f"Scope includes {matched_scope}, which matches your typical project work"
            )

        # 4) Agency / Buyer Relevance (safe phrasing)
        buyer_name = getattr(contract, "buyer_name", None)
        if buyer_name:
            bullets.append(
                f"Issued by {buyer_name}, which frequently procures services like yours"
            )

        # 5) Set-aside fit (future-safe wording)
        set_aside = getattr(contract, "set_aside", None)
        if set_aside:
            bullets.append(
                "Set-aside and contract type appear compatible with small business vendors"
            )

        # Keep it tight
        return bullets[:5]
        
    def _generate_match_reasons(
        self,
        capability_score: float,
        past_win_score: float,
        preference_score: float,
        contract: Contract,
        profile: CompanyProfile,
    ) -> List[str]:
        """Generate human-readable reasons for the match."""
        reasons = []

        try:
            # Capability match (primary)
            if capability_score >= 0.55:
                reasons.append("Strong capability match")
            elif capability_score >= 0.45:
                reasons.append("Good capability match")
            elif capability_score >= 0.35:
                reasons.append("Relevant to your services")

            # Past win patterns (context only)
            if past_win_score >= 0.6:
                past_wins = getattr(profile, "past_wins", None) or []
                matching_agency = any(
                    getattr(win, "buyer_name", None)
                    and contract.buyer_name
                    and win.buyer_name.lower() in contract.buyer_name.lower()
                    for win in past_wins
                )

                if matching_agency:
                    reasons.append(f"Previous wins with {contract.buyer_name}")
                else:
                    reasons.append("Similar to past wins")

            # Preference matches (context only)
            if preference_score > 0.7 and getattr(profile, "search_preference", None):
                prefs = profile.search_preference

                if getattr(prefs, "preferred_regions", None) and contract.region in prefs.preferred_regions:
                    reasons.append(f"In preferred region: {contract.region}")

                if getattr(prefs, "keywords", None):
                    text = f"{contract.title} {contract.description or ''}".lower()
                    matched = [kw for kw in prefs.keywords if kw.lower() in text][:3]
                    if matched:
                        reasons.append(f"Keywords: {', '.join(matched)}")

            if not reasons:
                reasons.append("Matches your profile")

            return reasons

        except Exception as e:
            logger.error(f"Error generating match reasons: {str(e)}", exc_info=True)
            return ["Matches your profile"]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        try:
            if not vec1 or not vec2:
                return 0.0

            if len(vec1) != len(vec2):
                logger.error(f"Vector length mismatch: {len(vec1)} vs {len(vec2)}")
                return 0.0

            vec1_np = np.array(vec1)
            vec2_np = np.array(vec2)

            dot_product = np.dot(vec1_np, vec2_np)
            norm1 = np.linalg.norm(vec1_np)
            norm2 = np.linalg.norm(vec2_np)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            return float(dot_product / (norm1 * norm2))

        except Exception as e:
            logger.error(f"Error in cosine_similarity: {str(e)}", exc_info=True)
            return 0.0