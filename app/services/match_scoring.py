"""
Contract Match Scoring Service

PURE CAPABILITY SCORING APPROACH WITH STRATEGIC INTELLIGENCE:
- match_score = capability similarity only (rescaled for display)
- Strategic intelligence (incumbent, pricing, competition) added as context
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
from app.models.company import CompanyProfile, OpportunityChain
from app.models.contract import Contract
from app.services.domain_filter import get_domain_filter
from app.services.incumbent_matcher import IncumbentMatcher
import numpy as np

logger = logging.getLogger(__name__)


class ContractMatchScorer:
    """
    Calculate personalized match scores for contracts with strategic intelligence.

    Scoring Philosophy:
    - match_score = capability similarity ONLY (rescaled)
    - Missing data (past wins, prefs) = no penalty to score
    - Strategic intelligence (incumbent/pricing/competition) provides context
    - Past wins and preferences provide context badges, not score impact
    """

    # Rescaling constants
    MIN_RAW = 0.35      # Lowest raw score we consider a match
    MAX_RAW = 0.75      # Exceptional raw score (rare)
    MIN_DISPLAY = 0.50  # Floor display score
    MAX_DISPLAY = 0.92  # Ceiling display score (never 99%)

    def __init__(self, db: Session, vector_client):
        self.db = db
        self.domain_filter = get_domain_filter()  
        logger.info("🔧 Domain filter initialized successfully")

        # Auto-detect client type (Pinecone or Qdrant)
        if hasattr(vector_client, "fetch"):
            self.pinecone_index = vector_client
            self.qdrant_client = None
            self.using_pinecone = True
        else:
            self.qdrant_client = vector_client
            self.pinecone_index = None
            self.using_pinecone = False
        
        # Initialize incumbent matcher for strategic intelligence
        self.incumbent_matcher = IncumbentMatcher(db, vector_client)
        logger.info("🎯 Incumbent matcher initialized successfully")

    def score_contract(
        self,
        contract: Contract,
        firm_id: str,
        capability_vectors: Optional[Dict] = None,
        contract_vectors: Optional[Dict] = None,
        past_win_vectors: Optional[Dict[str, List[float]]] = None,
        skip_strategic_intel: bool = False,  # ← NEW PARAMETER
    ) -> Optional[Dict]:
        """
        Calculate match score for a contract with optional strategic intelligence.
        
        Args:
            skip_strategic_intel: If True, skip incumbent/pricing/competition queries.
                                 Used in Phase 1 cache updates for speed (2-5 min).
                                 Phase 2 enrichment adds strategic intel later.
        
        NOW WITH:
        - Domain filtering to prevent cross-domain false positives
        - Incumbent detection (who currently holds similar contracts)
        - Pricing benchmarks (typical award amounts)
        - Competition analysis (avg number of bidders)
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

            # STEP 1: Apply preference filters (existing)
            if not self._passes_preference_filters(contract, profile):
                return None
            
            # STEP 2: Apply domain filter before expensive semantic scoring
            if not self.domain_filter.passes_domain_filter(contract, profile):
                logger.debug(
                    f"Filtered out {contract.notice_id}: domain mismatch "
                    f"({contract.title[:60]}...)"
                )
                return None

            # STEP 3: Calculate semantic scores (existing logic)
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

            # ✅ STEP 4: CONDITIONAL strategic intelligence
            incumbent_data = None
            pricing_benchmarks = None
            competition_stats = None
            
            if not skip_strategic_intel:
                # FULL STRATEGIC INTELLIGENCE (Phase 2 enrichment)
                logger.debug(f"Including strategic intelligence for {contract.notice_id}")
                
                # Try to get incumbent data (requires OpportunityChain match)
                opp_chain = self._contract_to_opportunity_chain(contract)
                if opp_chain:
                    try:
                        incumbent_data = self.incumbent_matcher.find_incumbent(opp_chain)
                        if incumbent_data:
                            logger.debug(f"Found incumbent for {contract.notice_id}: {incumbent_data.get('incumbent_name')}")
                    except Exception as e:
                        logger.error(f"Error finding incumbent for {contract.notice_id}: {e}")
                
                # Get pricing benchmarks and competition stats (works for ALL contracts with NAICS)
                if contract.naics_code and contract.buyer_name:
                    try:
                        pricing_benchmarks = self.incumbent_matcher.get_pricing_benchmarks(
                            contract.naics_code, 
                            contract.buyer_name
                        )
                        if pricing_benchmarks and pricing_benchmarks.get("sample_size", 0) > 0:
                            logger.debug(
                                f"Pricing benchmarks for {contract.notice_id}: "
                                f"${pricing_benchmarks.get('avg_award', 0)/1_000_000:.1f}M avg "
                                f"(n={pricing_benchmarks.get('sample_size')})"
                            )
                    except Exception as e:
                        logger.error(f"Error getting pricing benchmarks for {contract.notice_id}: {e}")
                    
                    try:
                        competition_stats = self.incumbent_matcher.get_competition_stats(
                            contract.naics_code,
                            contract.buyer_name
                        )
                        if competition_stats and competition_stats.get("avg_offers"):
                            logger.debug(
                                f"Competition stats for {contract.notice_id}: "
                                f"avg {competition_stats.get('avg_offers'):.1f} bidders"
                            )
                    except Exception as e:
                        logger.error(f"Error getting competition stats for {contract.notice_id}: {e}")
                elif not contract.naics_code:
                    logger.debug(f"⚠️ NO NAICS DATA - Skipping strategic intel for: {contract.notice_id}")
            else:
                # SKIP STRATEGIC INTELLIGENCE (Phase 1 fast caching)
                logger.debug(f"⚡ Skipping strategic intelligence for {contract.notice_id} (fast mode)")

            # Generate match explanations with strategic intelligence
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

                # Matched capability examples (top 1–3)
                "matched_capabilities": matched_capabilities,

                # NEW: Strategic intelligence (None if skipped)
                "incumbent_data": incumbent_data,
                "pricing_benchmarks": pricing_benchmarks,
                "competition_stats": competition_stats,

                # Enhanced match explanation with strategic intel
                "why_this_matches": self._generate_why_this_matches(
                    matched_capabilities=matched_capabilities,
                    contract=contract,
                    profile=profile,
                    raw_capability_score=raw_capability_score,
                    incumbent_data=incumbent_data,
                    pricing_benchmarks=pricing_benchmarks,
                    competition_stats=competition_stats
                ),

                # Context
                "match_reasons": match_reasons,

                # Legacy field for backward compatibility
                "total_score": round(display_score, 3),
            }

        except Exception as e:
            self.db.rollback()
            logger.error(
                f"Error scoring contract {getattr(contract, 'notice_id', '')}: {str(e)}",
                exc_info=True,
            )
            return None

    def _contract_to_opportunity_chain(self, contract: Contract) -> Optional[OpportunityChain]:
        """
        Convert Contract to OpportunityChain for incumbent matching.
        
        Returns existing OpportunityChain if found in database, None otherwise.
        This is normal - not all Pinecone contracts have OpportunityChain records.
        """
        try:
            # Try to find existing opportunity chain by notice_id
            opp = self.db.query(OpportunityChain).filter(
                OpportunityChain.base_notice_id == contract.notice_id
            ).first()
            
            if opp:
                logger.debug(f"Found OpportunityChain for {contract.notice_id}")
            
            return opp  # Returns None if not found
            
        except Exception as e:
            logger.error(f"Error converting contract to opportunity chain: {e}")
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
        profile: CompanyProfile,
        raw_capability_score: float,
        incumbent_data: Optional[Dict] = None,
        pricing_benchmarks: Optional[Dict] = None,
        competition_stats: Optional[Dict] = None
    ) -> List[str]:
        """
        Generate specific, evidence-based match explanations with strategic intelligence.
        Each bullet should be VERIFIABLE and SPECIFIC.
        
        NEW: Includes incumbent warnings, pricing context, and competition analysis.
        """
        bullets: List[str] = []

        # 1) INCUMBENT WARNING (if high/medium confidence)
        if incumbent_data and incumbent_data.get("confidence") in ["high", "medium"]:
            incumbent_name = incumbent_data["incumbent_name"]
            amount = incumbent_data.get("award_amount")
            ends = incumbent_data.get("contract_end")
            
            if incumbent_data.get("is_recompete"):
                warning = f"⚠️ RECOMPETE: {incumbent_name} incumbent"
                if amount:
                    warning += f" (${amount/1_000_000:.1f}M)"
                if ends:
                    warning += f", expires {ends[:7]}"
                bullets.append(warning)
            else:
                info = f"ℹ️ {incumbent_name} holds similar contract"
                if amount:
                    info += f" (${amount/1_000_000:.1f}M)"
                bullets.append(info)
        
        # 2) PRICING CONTEXT (if available with good sample size)
        if pricing_benchmarks and pricing_benchmarks.get("sample_size", 0) >= 3:
            avg = pricing_benchmarks.get("avg_award")
            min_val = pricing_benchmarks.get("min_award")
            max_val = pricing_benchmarks.get("max_award")
            n = pricing_benchmarks["sample_size"]
            
            if avg and min_val and max_val:
                bullets.append(
                    f"💰 Typical awards: ${min_val/1_000_000:.1f}M-${max_val/1_000_000:.1f}M "
                    f"(avg ${avg/1_000_000:.1f}M, n={n})"
                )
        
        # 3) COMPETITION LEVEL
        if competition_stats and competition_stats.get("avg_offers"):
            avg_offers = competition_stats["avg_offers"]
            if avg_offers >= 8:
                bullets.append(f"🔥 High competition (avg {avg_offers:.0f} bidders)")
            elif avg_offers >= 5:
                bullets.append(f"🎯 Moderate competition (avg {avg_offers:.0f} bidders)")
            else:
                bullets.append(f"✅ Lower competition (avg {avg_offers:.0f} bidders)")

        # 4) CAPABILITY MATCH - Show actual matched capability text
        if matched_capabilities and raw_capability_score >= 0.40:
            # Take first matched capability (highest scoring)
            top_capability = matched_capabilities[0]
            
            # Extract key phrase from contract description (first 80 chars)
            contract_excerpt = ""
            if contract.description:
                # Find first sentence or take first 80 chars
                first_sentence = contract.description.split('.')[0][:80]
                contract_excerpt = first_sentence.strip()
            
            if contract_excerpt:
                bullets.append(
                    f"Contract requires '{contract_excerpt}...' - matches your capability: '{top_capability[:80]}'"
                )
            else:
                bullets.append(f"Matches your core capability: {top_capability[:100]}")
        elif matched_capabilities:
            bullets.append(f"Matches your capability: {matched_capabilities[0][:100]}")
        else:
            bullets.append("Matches your core capabilities and services")

        # 5) NAICS ALIGNMENT - Check if exact match with company codes
        if contract.naics_code:
            if contract.naics_code in (profile.naics_codes or []):
                bullets.append(
                    f"NAICS {contract.naics_code} (your primary code) - you're pre-qualified"
                )
            else:
                bullets.append(
                    f"NAICS {contract.naics_code} aligns with your service areas"
                )

        # 6) PAST PERFORMANCE - Show similar wins
        if profile.past_wins:
            # Find similar past wins (same agency)
            similar_wins = []
            for win in profile.past_wins[:5]:
                if (contract.buyer_name and getattr(win, "buyer_name", None) and 
                    win.buyer_name.lower() in contract.buyer_name.lower()):
                    similar_wins.append(win)
            
            if similar_wins:
                win_names = [getattr(w, "contract_title", "")[:60] for w in similar_wins[:2]]
                bullets.append(
                    f"You've won similar work: {', '.join(win_names)}"
                )

        # 7) SET-ASIDE ELIGIBILITY - Check actual certifications
        if contract.set_aside:
            set_aside_lower = contract.set_aside.lower()
            
            # Check certifications
            is_eligible = False
            cert_type = ""
            
            if "sdvosb" in set_aside_lower and profile.sdvosb_certified:
                is_eligible = True
                cert_type = "SDVOSB"
            elif "8(a)" in set_aside_lower and profile.eight_a_certified:
                is_eligible = True
                cert_type = "8(a)"
            elif "wosb" in set_aside_lower and profile.wosb_certified:
                is_eligible = True
                cert_type = "WOSB"
            elif "hubzone" in set_aside_lower and profile.hubzone_certified:
                is_eligible = True
                cert_type = "HUBZone"
            elif "small business" in set_aside_lower and profile.sba_certified:
                is_eligible = True
                cert_type = "Small Business"
            
            if is_eligible:
                bullets.append(
                    f"Set-aside: {cert_type} (you're certified) - limited competition"
                )

        # 8) TIMELINE - Only mention if reasonable
        if contract.closing_date:
            try:
                from datetime import datetime
                if isinstance(contract.closing_date, str):
                    closing = datetime.fromisoformat(contract.closing_date.replace('Z', '+00:00'))
                else:
                    closing = contract.closing_date
                
                days_left = (closing - datetime.now(closing.tzinfo if hasattr(closing, 'tzinfo') else None)).days
                
                if 14 <= days_left <= 45:
                    bullets.append(
                        f"Closes in {days_left} days - enough time to prepare a quality response"
                    )
                elif 0 < days_left < 14:
                    bullets.append(
                        f"⚠️ Closes in {days_left} days - tight timeline, prioritize if highly relevant"
                    )
            except:
                pass  # Skip if date parsing fails

        # Keep it tight - max 5 bullets
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