"""
SAM.GOV Contract Match Scoring Service
Adapted for US Federal procurement with NAICS codes, set-asides, and PSC codes
Updated to use Pinecone for contract vectors and Qdrant for capability vectors
"""
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference
from app.models.contract import Contract
from qdrant_client import QdrantClient
import numpy as np
import logging

logger = logging.getLogger(__name__)


class SAMContractMatchScorer:
    """
    Scores SAM.GOV federal contract opportunities against company profiles.
    
    Scoring Components (US Federal Focus):
    - 40% Capability matching (semantic similarity + NAICS/PSC alignment)
    - 35% Past performance (federal experience, similar buyers, contract size)
    - 15% Set-aside eligibility (critical for small businesses)
    - 10% Preferences (location, value range, keywords)
    """
    
    def __init__(self, db: Session, qdrant_client: QdrantClient):
        self.db = db
        self.qdrant = qdrant_client
    
    def score_contract(
        self, 
        contract: Contract, 
        firm_id: str,
        sam_metadata: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Calculate match score for SAM.GOV contract against company profile.
        
        Args:
            contract: Contract object from search results
            firm_id: Company firm identifier
            sam_metadata: Optional SAM-specific fields (NAICS, set-aside, PSC)
        
        Returns:
            None if contract fails hard filters
            Dict with scores and match reasons if contract passes
        """
        
        # Load company profile
        profile = self.db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == firm_id
        ).first()
        
        if not profile:
            logger.debug(f"No company profile found for firm {firm_id}")
            return None
        
        # Initialize scoring structure
        scores = {
            "capability_score": 0.0,
            "past_performance_score": 0.0,
            "set_aside_score": 0.0,
            "preference_score": 0.0,
            "total_score": 0.0,
            "match_reasons": [],
            "eligibility_warnings": []
        }
        
        # Extract SAM metadata if provided
        if not sam_metadata:
            sam_metadata = {}
        
        # 1. SET-ASIDE ELIGIBILITY CHECK (15% - CRITICAL for small businesses)
        set_aside_score, set_aside_eligible, set_aside_reasons = self._check_set_aside_eligibility(
            sam_metadata.get('set_aside_code'),
            profile
        )
        scores["set_aside_score"] = set_aside_score
        scores["match_reasons"].extend(set_aside_reasons)
        
        # If set-aside restricted and company not eligible, return low score
        if not set_aside_eligible:
            scores["eligibility_warnings"].append(
                f"⚠️ Restricted to {sam_metadata.get('set_aside', 'certified businesses')} - verify eligibility"
            )
            # Don't filter out completely, but heavily penalize
            scores["set_aside_score"] = 0.0
        
        # 2. CAPABILITY MATCHING (40% - Semantic + NAICS/PSC alignment)
        capability_score, cap_reasons = self._calculate_capability_score(
            contract, 
            profile.capabilities,
            sam_metadata.get('naics_code'),
            sam_metadata.get('psc_code'),
            profile
        )
        scores["capability_score"] = capability_score
        scores["match_reasons"].extend(cap_reasons)
        
        # 3. PAST PERFORMANCE (35% - Federal experience heavily weighted)
        past_perf_score, perf_reasons = self._calculate_past_performance_score(
            contract,
            profile.past_wins,
            sam_metadata.get('department'),
            profile
        )
        scores["past_performance_score"] = past_perf_score
        scores["match_reasons"].extend(perf_reasons)
        
        # 4. SEARCH PREFERENCES (10% - Location, value, keywords)
        pref_score, passes_filters, pref_reasons = self._calculate_preference_score(
            contract,
            profile.search_preference,
            sam_metadata
        )
        scores["preference_score"] = pref_score
        scores["match_reasons"].extend(pref_reasons)
        
        # Hard filter: Don't return contracts that fail preferences
        if not passes_filters:
            logger.debug(f"Contract {contract.notice_id} failed preference filters")
            return None
        
        # Calculate weighted total score (US Federal weights)
        scores["total_score"] = (
            capability_score * 0.40 +
            past_perf_score * 0.35 +
            set_aside_score * 0.15 +
            pref_score * 0.10
        )
        
        # Add overall assessment
        if scores["total_score"] >= 0.70:
            scores["match_reasons"].insert(0, "🎯 Excellent match - highly qualified")
        elif scores["total_score"] >= 0.50:
            scores["match_reasons"].insert(0, "✓ Good match - strong contender")
        elif scores["total_score"] >= 0.30:
            scores["match_reasons"].insert(0, "⚡ Potential match - consider capabilities")
        
        logger.info(
            f"SAM Contract {contract.notice_id} scored {scores['total_score']:.2%} "
            f"for firm {firm_id} (cap:{capability_score:.2f}, perf:{past_perf_score:.2f})"
        )
        
        return scores
    
    def _check_set_aside_eligibility(
        self,
        set_aside_code: Optional[str],
        profile: CompanyProfile
    ) -> tuple[float, bool, List[str]]:
        """
        Check if company is eligible for contract's set-aside designation.
        
        US Federal set-asides are HARD REQUIREMENTS - if restricted, only
        eligible companies can bid.
        """
        reasons = []
        
        if not set_aside_code or set_aside_code == "":
            # Unrestricted competition - anyone can bid
            return 1.0, True, ["Open competition - no restrictions"]
        
        # Map set-aside codes to profile fields
        set_aside_map = {
            "SBA": ("sba_certified", "Small Business"),
            "SDVOSB": ("sdvosb_certified", "Service-Disabled Veteran-Owned"),
            "WOSB": ("wosb_certified", "Women-Owned Small Business"),
            "8A": ("eight_a_certified", "8(a) Business Development"),
            "HUBZONE": ("hubzone_certified", "HUBZone")
        }
        
        if set_aside_code in set_aside_map:
            cert_field, cert_name = set_aside_map[set_aside_code]
            is_certified = getattr(profile, cert_field, False)
            
            if is_certified:
                reasons.append(f"✓ Eligible: {cert_name} certified")
                return 1.0, True, reasons
            else:
                reasons.append(f"⚠️ Requires {cert_name} certification")
                return 0.0, False, reasons
        
        # Unknown set-aside code - assume not eligible
        return 0.0, False, [f"⚠️ Restricted to {set_aside_code}"]
    
    def _calculate_capability_score(
        self,
        contract: Contract,
        capabilities: List[CompanyCapability],
        naics_code: Optional[str],
        psc_code: Optional[str],
        profile: CompanyProfile
    ) -> tuple[float, List[str]]:
        """
        Score based on semantic similarity + NAICS/PSC code alignment.
        
        US Federal specific: NAICS codes are critical for determining eligibility
        and past performance relevance.
        
        Contract vectors retrieved from Pinecone, capability vectors from Qdrant.
        """
        if not capabilities:
            return 0.0, ["⚠️ Add company capabilities to improve matching"]
        
        reasons = []
        semantic_score = 0.0
        naics_bonus = 0.0
        psc_bonus = 0.0
        
        # 1. SEMANTIC SIMILARITY - Fetch contract from Pinecone, capabilities from Qdrant
        if contract.qdrant_id:
            try:
                from app.services.pinecone_store import PineconeStoreService
                from app.core.config import settings
                
                # Initialize Pinecone
                pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
                
                # Fetch contract vector from Pinecone
                result = pinecone.index.fetch(ids=[contract.qdrant_id])
                
                if result and result.vectors and contract.qdrant_id in result.vectors:
                    contract_vector = result.vectors[contract.qdrant_id].values
                    similarities = []
                    
                    # Compare against each capability from Qdrant
                    for cap in capabilities:
                        if cap.qdrant_id:
                            cap_points = self.qdrant.retrieve(
                                collection_name="capabilities",
                                ids=[cap.qdrant_id],
                                with_vectors=True
                            )
                            if cap_points:
                                cap_vector = cap_points[0].vector
                                similarity = self._cosine_similarity(contract_vector, cap_vector)
                                similarities.append((similarity, cap.capability_text))
                    
                    if similarities:
                        # Use top 3 matches average
                        similarities.sort(reverse=True, key=lambda x: x[0])
                        top_matches = similarities[:3]
                        semantic_score = sum(s[0] for s in top_matches) / len(top_matches)
                        
                        # Add reason for best match
                        best_match = top_matches[0]
                        if best_match[0] > 0.6:
                            reasons.append(f"Strong capability match: '{best_match[1][:50]}' ({best_match[0]:.0%})")
                        elif best_match[0] > 0.4:
                            reasons.append(f"Good capability match: '{best_match[1][:50]}' ({best_match[0]:.0%})")
                else:
                    logger.warning(f"Contract vector not found in Pinecone: {contract.qdrant_id}")
            
            except Exception as e:
                logger.error(f"Capability semantic scoring error: {str(e)}", exc_info=True)
        
        # 2. NAICS CODE ALIGNMENT (US Federal specific)
        if naics_code and hasattr(profile, 'naics_codes') and profile.naics_codes:
            # Check if company's NAICS codes match contract
            matching_naics = [code for code in profile.naics_codes if code.startswith(naics_code[:2])]
            if matching_naics:
                naics_bonus = 0.2  # 20% bonus for NAICS alignment
                reasons.append(f"✓ NAICS code match ({naics_code})")
        
        # 3. PSC CODE ALIGNMENT (Product Service Code)
        if psc_code and hasattr(profile, 'psc_codes') and profile.psc_codes:
            if psc_code in profile.psc_codes:
                psc_bonus = 0.15  # 15% bonus for PSC match
                reasons.append(f"✓ PSC code match ({psc_code})")
        
        # Combine scores (semantic is base, NAICS/PSC are bonuses)
        final_score = min(semantic_score + naics_bonus + psc_bonus, 1.0)
        
        return final_score, reasons
    
    def _calculate_past_performance_score(
        self,
        contract: Contract,
        past_wins: List[PastWin],
        department: Optional[str],
        profile: CompanyProfile
    ) -> tuple[float, List[str]]:
        """
        Score based on past performance - CRITICAL for federal contracts.
        
        US Federal weighting:
        - Federal experience: 40% (vs 0% for first-time bidders)
        - Same agency/department: 30%
        - Similar contract value: 20%
        - Recent performance (last 3 years): 10%
        """
        if not past_wins:
            return 0.0, ["⚠️ Add past contract wins to demonstrate experience"]
        
        score = 0.0
        reasons = []
        
        # Federal experience baseline
        federal_experience = getattr(profile, 'federal_experience', False)
        if federal_experience:
            score += 0.40
            reasons.append("✓ Proven federal contracting experience")
        else:
            # Check if any past wins are federal
            federal_keywords = ["department of", "dept of", "federal", "government", "GSA", "DOD", "DHS"]
            has_federal_win = any(
                any(kw in win.buyer_name.lower() for kw in federal_keywords)
                for win in past_wins if win.buyer_name
            )
            if has_federal_win:
                score += 0.20
                reasons.append("✓ Some federal contracting experience")
        
        # Match by agency/department
        if department and contract.buyer_name:
            for win in past_wins:
                if win.buyer_name:
                    buyer_lower = contract.buyer_name.lower()
                    win_buyer_lower = win.buyer_name.lower()
                    
                    # Exact agency match (huge plus)
                    if win_buyer_lower in buyer_lower or buyer_lower in win_buyer_lower:
                        score += 0.30
                        reasons.append(f"✓ Past performance with {win.buyer_name[:40]}")
                        break
                    
                    # Same parent department (e.g., both DHS)
                    dept_keywords = ["department of", "dept of"]
                    for keyword in dept_keywords:
                        if keyword in buyer_lower and keyword in win_buyer_lower:
                            dept1 = buyer_lower.split(keyword)[1].split()[0]
                            dept2 = win_buyer_lower.split(keyword)[1].split()[0]
                            if dept1 == dept2:
                                score += 0.15
                                reasons.append(f"✓ Experience with same department")
                                break
        
        # Match by contract value (within 3x range for federal contracts)
        if contract.contract_value:
            for win in past_wins:
                if win.contract_value:
                    contract_val = float(contract.contract_value)
                    win_val = float(win.contract_value)
                    
                    value_ratio = min(contract_val, win_val) / max(contract_val, win_val)
                    if value_ratio > 0.33:  # Within 3x range
                        score += 0.20
                        reasons.append(f"✓ Similar contract size (${win_val:,.0f})")
                        break
        
        # Recent performance bonus (contracts within last 3 years)
        from datetime import datetime, timedelta, date
        three_years_ago = datetime.now() - timedelta(days=3*365)
        three_years_ago_date = three_years_ago.date()
        
        recent_wins = []
        for win in past_wins:
            if win.award_date:
                if isinstance(win.award_date, datetime):
                    if win.award_date > three_years_ago:
                        recent_wins.append(win)
                elif isinstance(win.award_date, date):
                    if win.award_date > three_years_ago_date:
                        recent_wins.append(win)
        
        if recent_wins:
            score += 0.10
            reasons.append(f"✓ Recent performance ({len(recent_wins)} wins in last 3 years)")
        
        # Cap at 1.0
        final_score = min(score, 1.0)
        
        return final_score, reasons
    
    def _calculate_preference_score(
        self,
        contract: Contract,
        preferences: Optional[SearchPreference],
        sam_metadata: Dict
    ) -> tuple[float, bool, List[str]]:
        """
        Apply search preferences - adapted for US states and dollar values.
        """
        if not preferences:
            return 1.0, True, []
        
        passes_filters = True
        score = 1.0
        reasons = []
        
        # Value range filter (hard)
        if contract.contract_value:
            if preferences.min_contract_value and contract.contract_value < preferences.min_contract_value:
                passes_filters = False
            
            if preferences.max_contract_value and contract.contract_value > preferences.max_contract_value:
                passes_filters = False
            
            if passes_filters and (preferences.min_contract_value or preferences.max_contract_value):
                reasons.append(f"✓ Value ${contract.contract_value:,.0f} in range")
        
        # Excluded categories (hard)
        if preferences.excluded_categories:
            contract_text = f"{contract.title} {contract.description or ''}".lower()
            for category in preferences.excluded_categories:
                if category.lower() in contract_text:
                    passes_filters = False
                    break
        
        # State/region preference (soft - US states)
        if preferences.preferred_regions and contract.region:
            if contract.region in preferences.preferred_regions:
                score += 0.2
                reasons.append(f"✓ Preferred state: {contract.region}")
            else:
                score *= 0.7  # Penalty for non-preferred state
        
        # Keyword matching (soft)
        if preferences.keywords:
            contract_text = f"{contract.title} {contract.description or ''}".lower()
            matched_keywords = [kw for kw in preferences.keywords if kw.lower() in contract_text]
            
            if matched_keywords:
                keyword_boost = min(len(matched_keywords) * 0.1, 0.3)
                score += keyword_boost
                reasons.append(f"✓ Keywords: {', '.join(matched_keywords[:2])}")
        
        final_score = min(score, 1.0)
        return final_score, passes_filters, reasons
    
    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        vec1_arr = np.array(vec1)
        vec2_arr = np.array(vec2)
        
        dot_product = np.dot(vec1_arr, vec2_arr)
        norm_product = np.linalg.norm(vec1_arr) * np.linalg.norm(vec2_arr)
        
        if norm_product == 0:
            return 0.0
        
        return float(dot_product / norm_product)
    
    def get_improvement_recommendations(
        self, 
        firm_id: str
    ) -> List[Dict]:
        """
        Generate US Federal-specific recommendations to improve match scores.
        """
        profile = self.db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == firm_id
        ).first()
        
        if not profile:
            return []
        
        recommendations = []
        
        # 1. FEDERAL EXPERIENCE (35% weight)
        federal_exp = getattr(profile, 'federal_experience', False)
        past_wins_count = len(profile.past_wins) if profile.past_wins else 0
        
        if not federal_exp and past_wins_count == 0:
            recommendations.append({
                "category": "past_performance",
                "priority": "critical",
                "action": "Add past federal contract wins to demonstrate capability",
                "impact": "+35% to match scores",
                "icon": "🏛️",
                "specific_actions": [
                    "Add any past federal contracts (GSA, DOD, DHS, etc.)",
                    "Include contract numbers and agency names",
                    "Even subcontract experience counts"
                ]
            })
        elif past_wins_count < 3:
            recommendations.append({
                "category": "past_performance",
                "priority": "high",
                "action": f"Add {3 - past_wins_count} more federal wins for credibility",
                "impact": f"+{(3 - past_wins_count) * 10}% potential boost",
                "icon": "📈"
            })
        
        # 2. SET-ASIDE CERTIFICATIONS (15% weight)
        certifications = {
            "sba_certified": "Small Business (SBA)",
            "sdvosb_certified": "Service-Disabled Veteran-Owned (SDVOSB)",
            "wosb_certified": "Women-Owned Small Business (WOSB)",
            "eight_a_certified": "8(a) Business Development",
            "hubzone_certified": "HUBZone"
        }
        
        uncertified = [
            name for field, name in certifications.items()
            if not getattr(profile, field, False)
        ]
        
        if uncertified:
            recommendations.append({
                "category": "certifications",
                "priority": "high",
                "action": "Get set-aside certifications to access restricted contracts",
                "impact": "+15% on eligible contracts",
                "icon": "🎖️",
                "specific_actions": [
                    f"Apply for {cert}" for cert in uncertified[:2]
                ] + ["30-50% of federal contracts are set-aside restricted"]
            })
        
        # 3. NAICS/PSC CODES (impacts 40% capability score)
        has_naics = hasattr(profile, 'naics_codes') and profile.naics_codes
        has_psc = hasattr(profile, 'psc_codes') and profile.psc_codes
        
        if not has_naics:
            recommendations.append({
                "category": "classifications",
                "priority": "medium",
                "action": "Add NAICS codes for your services",
                "impact": "+20% on matching contracts",
                "icon": "🏷️",
                "specific_actions": [
                    "Find your NAICS codes at census.gov",
                    "Add primary and secondary NAICS",
                    "Example: 541512 (Computer Systems Design)"
                ]
            })
        
        # 4. CAPABILITIES (40% weight)
        cap_count = len(profile.capabilities) if profile.capabilities else 0
        if cap_count < 3:
            recommendations.append({
                "category": "capabilities",
                "priority": "high",
                "action": f"Add {3 - cap_count} specific capabilities",
                "impact": "+15-20% relevance",
                "icon": "💡",
                "specific_actions": [
                    "Use exact terminology from SAM.GOV contracts",
                    "Be specific: 'FedRAMP Cloud Migration' not 'IT Services'",
                    "Include security clearance level if applicable"
                ]
            })
        
        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recommendations.sort(key=lambda x: priority_order[x["priority"]])
        
        return recommendations