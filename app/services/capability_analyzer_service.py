"""
BidMatch Capability Analyzer Service

Analyzes company capabilities against near-miss contracts to generate
improvement recommendations grounded in real contract language.

CRITICAL PRINCIPLES:
- Teaches contract language, not score optimization
- Enhancement > Addition
- Evidence in words, not numbers
- Max 5 recommendations, 1-2 high priority
"""

import logging
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from openai import AsyncOpenAI
from collections import Counter
import json

from app.models.company import CompanyProfile, CompanyCapability
from app.services.pinecone_store import PineconeStoreService
from app.services.llm import get_llm_service
from app.core.config import settings

logger = logging.getLogger(__name__)


class CapabilityAnalyzerService:
    """Analyze capability gaps and generate contract-grounded recommendations"""
    
    # Profile state classifications
    PROFILE_STATES = {
        "too_generic": "Your capabilities are broad, but contracts use more technical language.",
        "missing_federal_language": "Your capabilities lack specific federal terminology and frameworks.",
        "strong_but_narrow": "Your capabilities are well-defined but may miss adjacent opportunities.",
        "well_aligned": "Your capabilities align well with contract language."
    }
    
    def __init__(self, db: Session, pinecone_service: PineconeStoreService):
        self.db = db
        self.pinecone = pinecone_service
        self.llm_service = get_llm_service()
        self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    async def analyze_capability_gaps(
        self, 
        firm_id: str,
        max_recommendations: int = 5
    ) -> Dict:
        """
        Main entry point: Analyze capability gaps and return recommendations.
        
        Args:
            firm_id: Company identifier
            max_recommendations: Max recommendations to return (default 5)
        
        Returns:
            Dict following the recommendation schema from the brief
        """
        try:
            # Get company profile
            profile = self.db.query(CompanyProfile).filter(
                CompanyProfile.firm_id == firm_id
            ).first()
            
            if not profile:
                logger.error(f"No profile found for firm {firm_id}")
                return self._empty_response(firm_id)
            
            # Get near-miss contracts (relative ranking approach)
            near_miss_contracts = await self._get_near_miss_contracts(profile)
            
            if not near_miss_contracts:
                logger.warning(f"No near-miss contracts found for {firm_id}")
                return self._empty_response(firm_id)
            
            # Extract capability patterns from contracts
            capability_patterns = self._extract_capability_patterns(near_miss_contracts)
            
            # Classify profile state
            profile_state = await self._classify_profile_state(profile, capability_patterns)
            
            # Generate recommendations (returns dict with diagnosis and recommendations)
            result = await self._generate_recommendations(
                profile,
                near_miss_contracts,
                capability_patterns,
                max_recommendations
            )
            
            recommendations = result.get("recommendations", [])
            diagnosis = result.get("diagnosis", profile_state)
            diagnosis_detail = result.get("diagnosis_detail", profile_state)
            
            return {
                "analysis_context": {
                    "firm_id": firm_id,
                    "capabilities_analyzed": len(profile.capabilities or []),
                    "contracts_analyzed": len(near_miss_contracts),
                    "analysis_basis": "near_match_contracts",
                    "profile_diagnosis": diagnosis,
                    "profile_diagnosis_detail": diagnosis_detail
                },
                "recommendations": recommendations[:max_recommendations]
            }
        
        except Exception as e:
            logger.error(f"Error analyzing capabilities for {firm_id}: {e}", exc_info=True)
            return self._empty_response(firm_id)
    
    async def _get_near_miss_contracts(
        self, 
        profile: CompanyProfile,
        target_count: int = 50
    ) -> List[Dict]:
        """
        Get near-miss contracts using relative ranking approach.
        
        Strategy:
        1. Query with each capability vector
        2. Get top 100 results per capability
        3. Score them using existing match scoring
        4. Take contracts in the 40th-70th percentile range
        5. Return up to target_count unique contracts
        """
        try:
            capabilities = profile.capabilities
            
            if not capabilities:
                return []
            
            # Get capability vectors
            from app.services.capability_store_pinecone import get_capability_store
            cap_store = get_capability_store()
            
            capability_vectors = {}
            for cap in capabilities:
                if cap.qdrant_id:  # Actually pinecone_id
                    vector_data = cap_store.get_capability(cap.qdrant_id)
                    if vector_data:
                        capability_vectors[cap.qdrant_id] = vector_data["vector"]
            
            if not capability_vectors:
                logger.warning("No capability vectors found")
                return []
            
            # Query Pinecone with each capability
            all_contracts = {}
            for cap_id, vector in capability_vectors.items():
                results = self.pinecone.search_contracts(
                    query_vector=vector,
                    limit=100,
                    min_score=0.35,  # Low threshold to capture near-misses
                    namespace="contracts"
                )
                
                for contract in results:
                    notice_id = contract.get("notice_id")
                    if notice_id and notice_id not in all_contracts:
                        all_contracts[notice_id] = contract
            
            # Sort by score and take middle percentiles
            sorted_contracts = sorted(
                all_contracts.values(),
                key=lambda x: x.get("score", 0),
                reverse=True
            )
            
            # Take contracts in 40th-70th percentile (near-misses)
            total = len(sorted_contracts)
            if total < 10:
                # Not enough data, return what we have
                return sorted_contracts[:target_count]
            
            start_idx = int(total * 0.4)
            end_idx = int(total * 0.7)
            near_misses = sorted_contracts[start_idx:end_idx]
            
            logger.info(f"Found {len(near_misses)} near-miss contracts (from {total} total)")
            return near_misses[:target_count]
        
        except Exception as e:
            logger.error(f"Error getting near-miss contracts: {e}")
            return []
    
    def _extract_capability_patterns(self, contracts: List[Dict]) -> Dict:
        """
        Extract dominant capability language patterns from contracts.
        
        Returns:
            Dict with:
            - technical_terms: Most common technical terms
            - frameworks: Standards/frameworks mentioned
            - service_verbs: Action verbs used
            - agencies: Agency patterns
        """
        try:
            technical_terms = []
            frameworks = []
            service_verbs = []
            agencies = []
            
            # Common federal frameworks and standards (case-insensitive matching)
            FEDERAL_FRAMEWORKS = [
                "RMF", "Risk Management Framework", "ATO", "Authority to Operate",
                "NIST", "FedRAMP", "FISMA", "CMMC", "Zero Trust",
                "800-53", "800-171", "FIPS", "STIGs",
                "Agile", "DevSecOps", "CI/CD", "SAFe"
            ]
            
            # Service verbs common in contracts
            SERVICE_VERBS = [
                "implementation", "deployment", "migration", "modernization",
                "integration", "support", "maintenance", "consulting",
                "development", "design", "assessment", "analysis"
            ]
            
            for contract in contracts:
                text = f"{contract.get('title', '')} {contract.get('description', '')}".lower()
                
                # Extract frameworks
                for framework in FEDERAL_FRAMEWORKS:
                    if framework.lower() in text:
                        frameworks.append(framework)
                
                # Extract service verbs
                for verb in SERVICE_VERBS:
                    if verb in text:
                        service_verbs.append(verb)
                
                # Collect agencies
                agency = contract.get("agency", "")
                if agency:
                    agencies.append(agency)
            
            return {
                "frameworks": dict(Counter(frameworks).most_common(10)),
                "service_verbs": dict(Counter(service_verbs).most_common(10)),
                "agencies": dict(Counter(agencies).most_common(5)),
                "total_contracts": len(contracts)
            }
        
        except Exception as e:
            logger.error(f"Error extracting patterns: {e}")
            return {"frameworks": {}, "service_verbs": {}, "agencies": {}, "total_contracts": 0}
    
    async def _classify_profile_state(
        self,
        profile: CompanyProfile,
        patterns: Dict
    ) -> str:
        """
        Classify the company's capability profile state.
        
        Returns one of: too_generic, missing_federal_language, strong_but_narrow, well_aligned
        """
        try:
            capabilities = profile.capabilities or []
            
            if not capabilities:
                return "missing_federal_language"
            
            # Check for generic language
            generic_keywords = ["services", "solutions", "consulting", "support"]
            technical_keywords = list(patterns.get("frameworks", {}).keys())
            
            capability_text = " ".join([cap.capability_text.lower() for cap in capabilities])
            
            # Count generic vs technical terms
            generic_count = sum(1 for kw in generic_keywords if kw in capability_text)
            technical_count = sum(1 for kw in technical_keywords if kw.lower() in capability_text)
            
            # Classification logic
            if technical_count == 0 and generic_count > 5:
                return "too_generic"
            elif technical_count < 3:
                return "missing_federal_language"
            elif len(capabilities) < 4:
                return "strong_but_narrow"
            else:
                return "well_aligned"
        
        except Exception as e:
            logger.error(f"Error classifying profile state: {e}")
            return "missing_federal_language"
    
    async def _generate_recommendations(
        self,
        profile: CompanyProfile,
        contracts: List[Dict],
        patterns: Dict,
        max_count: int
    ) -> List[Dict]:
        """
        Generate save-ready capability recommendations using OpenAI.
        
        Returns list following the recommendation schema.
        """
        try:
            capabilities = profile.capabilities or []
            capability_texts = [cap.capability_text for cap in capabilities]
            
            # Prepare contract summaries (top patterns)
            contract_summaries = []
            for contract in contracts[:20]:  # Sample to avoid token limits
                contract_summaries.append({
                    "title": contract.get("title", "")[:200],
                    "agency": contract.get("agency", ""),
                    "naics": contract.get("naics_code", ""),
                    "description": contract.get("description", "")[:300]
                })
            
            # Build prompt
            prompt = self._build_analysis_prompt(
                capability_texts,
                contract_summaries,
                patterns
            )
            
            # Call OpenAI with GPT-5.2, fallback to GPT-4o if not available
            try:
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",  # Try GPT-5.2  first
                    messages=[
                        {
                            "role": "system",
                            "content": """You are a federal contracting expert analyzing capability gaps.

CRITICAL RULES:
1. Generate SAVE-READY capability statements (complete sentences, grammatically correct)
2. Ground every recommendation in actual contract language patterns
3. Prefer ENHANCING existing capabilities over adding new ones
4. Use federal terminology (frameworks, standards, agencies)
5. Write in professional capability statement format
6. NO marketing fluff or buzzwords
7. Return ONLY valid JSON with no markdown formatting

Focus on: technical specificity, federal frameworks, concrete deliverables."""
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
            except Exception as e:
                if "model_not_found" in str(e) or "does not exist" in str(e):
                    logger.warning(f"GPT-5.2 not available, falling back to GPT-4o: {e}")
                    # Fallback to GPT-4o
                    response = await self.openai_client.chat.completions.create(
                        model="gpt-4o-mini",  # Fallback to GPT-4o
                        messages=[
                            {
                                "role": "system",
                                "content": """You are a federal contracting expert analyzing capability gaps.

CRITICAL RULES:
1. Generate SAVE-READY capability statements (complete sentences, grammatically correct)
2. Ground every recommendation in actual contract language patterns
3. Prefer ENHANCING existing capabilities over adding new ones
4. Use federal terminology (frameworks, standards, agencies)
5. Write in professional capability statement format
6. NO marketing fluff or buzzwords
7. Return ONLY valid JSON with no markdown formatting

Focus on: technical specificity, federal frameworks, concrete deliverables."""
                            },
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.3,
                        response_format={"type": "json_object"}
                    )
                else:
                    raise  # Re-raise if it's a different error
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse and validate
            import json
            result = json.loads(result_text)
            
            # Extract diagnosis information
            diagnosis = result.get("diagnosis", "analyzed")
            diagnosis_detail = result.get("diagnosis_detail", "Analysis complete")
            recommendations = result.get("recommendations", [])
            
            # Validate and enrich each recommendation
            validated_recs = []
            for idx, rec in enumerate(recommendations[:max_count]):
                validated_rec = self._validate_recommendation(rec, capabilities, patterns, idx)
                if validated_rec:
                    validated_recs.append(validated_rec)
            
            return {
                "diagnosis": diagnosis,
                "diagnosis_detail": diagnosis_detail,
                "recommendations": validated_recs
            }
        
        except Exception as e:
            logger.error(f"Error generating recommendations: {e}", exc_info=True)
            return {
                "diagnosis": "error",
                "diagnosis_detail": "Unable to complete analysis",
                "recommendations": []
            }
    
    def _build_analysis_prompt(
        self,
        current_capabilities: List[str],
        contracts: List[Dict],
        patterns: Dict
    ) -> str:
        """Build the prompt for OpenAI capability analysis"""
        
        frameworks_list = ", ".join(list(patterns.get("frameworks", {}).keys())[:8])
        agencies_list = ", ".join(list(patterns.get("agencies", {}).keys())[:5])
        
        # Get sample contract snippets for evidence
        sample_snippets = []
        for contract in contracts[:5]:
            title = contract.get('title', '')[:100]
            agency = contract.get('agency', 'Federal Agency')
            sample_snippets.append(f"[{agency}] {title}")
        
        return f"""Analyze this company's capabilities against federal contract patterns and generate 3-5 improvement recommendations.

CURRENT CAPABILITIES:
{chr(10).join(f"{i+1}. {cap}" for i, cap in enumerate(current_capabilities))}

CONTRACT PATTERNS:
- Common frameworks: {frameworks_list}
- Top agencies: {agencies_list}
- Total contracts analyzed: {patterns.get('total_contracts', 0)}

SAMPLE CONTRACT TITLES (for evidence):
{chr(10).join(sample_snippets)}

CRITICAL INSTRUCTIONS:

1. STRUCTURE EACH RECOMMENDATION:
   - capability_statement: ONE clear sentence (15-25 words max)
   - deliverables: Array of concrete outputs (e.g., ["SSP", "POA&M", "SAR", "ISBP"])
   - frameworks_standards: Array of federal frameworks (e.g., ["RMF", "NIST 800-53", "FedRAMP"])
   - keywords: Array of key terms (e.g., ["continuous monitoring", "control evidence", "ATO"])
   
2. EXTRACT EVIDENCE SNIPPETS:
   - For each recommendation, include 1-2 SHORT phrases (10-15 words MAXIMUM) from typical solicitations
   - Focus on DELIVERABLE language (e.g., "develop and maintain SSPs, POA&Ms, and control evidence")
   - Format: {{"snippet_text": "short phrase under 15 words", "context": "DoD cloud security"}}
   
3. PRIORITIZATION:
   - high: Missing critical federal frameworks/deliverables
   - medium: Under-specified or needs more technical detail
   - low: Optional coverage expansion

4. ENHANCE vs ADD:
   - If enhancing: identify which existing capability (by index 0-based)
   - If adding: set related_existing_capability_index to null

5. DIAGNOSIS (choose one):
   - "missing_delivery_artifacts": Strong strategic positioning with opportunities to strengthen federal delivery language and compliance artifacts
   - "missing_federal_language": Strong strategic positioning with opportunities to strengthen federal delivery language and compliance artifacts
   - "too_generic": Clear positioning with opportunities to add specificity and operational deliverables
   - "strong_but_narrow": Strong alignment in core areas with opportunities to expand coverage across adjacent requirements
   - "well_aligned": Well-aligned positioning for federal opportunities
   
6. Return JSON in this EXACT format:
{{
  "diagnosis": "missing_delivery_artifacts",
  "diagnosis_detail": "Strong strategic positioning with opportunities to strengthen federal delivery language and compliance artifacts",
  "recommendations": [
    {{
      "capability_statement": "One clear sentence describing the capability",
      "deliverables": ["SSP", "POA&M", "SAR"],
      "frameworks_standards": ["RMF", "NIST 800-53"],
      "keywords": ["continuous monitoring", "control evidence"],
      "category": "Category name",
      "recommendation_type": "missing_capability" or "under_specified_capability" or "overly_generic_capability",
      "priority": "high" or "medium" or "low",
      "evidence_snippets": [
        {{
          "snippet_text": "Short 10-20 word phrase from typical solicitation",
          "context": "DoD cloud security solicitations"
        }}
      ],
      "related_existing_capability_index": null or 0,
      "action": "add" or "enhance"
    }}
  ]
}}

Remember: 
- Capability statements must be SAVE-READY (grammatically correct, professional)
- Deliverables = tangible outputs (documents, reports, plans)
- Frameworks = standards/methodologies (RMF, NIST, FedRAMP, CMMC)
- Keywords = key technical terms that appear in solicitations
- Evidence snippets = actual language from contracts (10-20 words max each)"""
    
    def _validate_recommendation(
        self,
        rec: Dict,
        existing_capabilities: List[CompanyCapability],
        patterns: Dict,
        rec_index: int
    ) -> Optional[Dict]:
        """Validate and enrich a recommendation to match the required schema"""
        
        try:
            # Extract fields from new chip-based format
            statement = rec.get('capability_statement', '')
            deliverables = rec.get('deliverables', [])
            frameworks = rec.get('frameworks_standards', [])
            keywords = rec.get('keywords', [])
            snippets = rec.get('evidence_snippets', [])
            category = rec.get("category", "General")
            rec_type = rec.get("recommendation_type", "missing_capability")
            priority = rec.get("priority", "medium")
            related_idx = rec.get("related_existing_capability_index")
            action = rec.get("action", "add")
            
            # Validate capability statement
            if not statement or len(statement) < 20:
                logger.warning(f"Recommendation {rec_index} has invalid capability statement")
                return None
            
            # Build full capability text for backward compatibility (used in "Add" action)
            # Format: statement only (chips displayed separately in UI)
            capability_text = statement
            
            # Build evidence from snippets
            evidence_list = []
            for snippet in snippets:
                snippet_text = snippet.get('snippet_text', '')
                context = snippet.get('context', '')
                if snippet_text:
                    # Format: snippet (context)
                    evidence_list.append(f"{snippet_text} ({context})" if context else snippet_text)
            
            # Fallback evidence if no snippets provided
            if not evidence_list:
                if frameworks:
                    evidence_list.append(f"Common in federal solicitations requiring {', '.join(frameworks[:2])}")
                else:
                    evidence_list.append("Common in federal contracting solicitations")
            
            # Build recommendation following the schema
            recommendation = {
                "id": f"cap_rec_{rec_index}",
                "type": "capability_gap",
                "priority": priority,
                "confidence": 0.8,
                "recommendation_category": rec_type,
                "suggested_capability": {
                    "capability_text": capability_text,  # Full text for adding
                    "capability_statement": statement,  # NEW: Just the core sentence
                    "deliverables": deliverables,  # NEW: Chip array
                    "frameworks_standards": frameworks,  # NEW: Chip array
                    "keywords": keywords,  # NEW: Chip array
                    "category": category,
                    "naics_code": None
                },
                "why_this_matters": {
                    "summary": evidence_list[0] if evidence_list else "Improves federal contract alignment",
                    "evidence": evidence_list,
                    "snippets": snippets  # NEW: Raw snippet objects for detailed view
                },
                "related_existing_capabilities": [],
                "recommended_action": action,
                "ui_hints": {
                    "primary_cta": "I offer this → Add capability" if action == "add" else "Update my capability",
                    "secondary_cta": "Not relevant"  # NEW: Dismissal option
                }
            }
            
            # Add related capability if enhancement
            if related_idx is not None and 0 <= related_idx < len(existing_capabilities):
                related_cap = existing_capabilities[related_idx]
                recommendation["related_existing_capabilities"].append({
                    "capability_id": related_cap.id,
                    "capability_text": related_cap.capability_text,
                    "suggested_action": "enhance"
                })
            
            return recommendation
        
        except Exception as e:
            logger.error(f"Error validating recommendation {rec_index}: {e}")
            return None
    
    def _empty_response(self, firm_id: str) -> Dict:
        """Return empty response when analysis cannot be performed"""
        return {
            "analysis_context": {
                "firm_id": firm_id,
                "capabilities_analyzed": 0,
                "contracts_analyzed": 0,
                "analysis_basis": "insufficient_data",
                "profile_diagnosis": "Insufficient data for analysis"
            },
            "recommendations": []
        }