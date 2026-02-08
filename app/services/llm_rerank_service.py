"""
LLM Re-Ranking Service - Phase 1.5 (Batch 1 Optimized)

Batch re-ranks semantic candidates using GPT-4o-mini with bid/no-bid decision framing.
Generates reasons that mirror how senior bid managers actually triage opportunities.

OPTIMIZATIONS FOR BATCH 1 (SME GOVCON FIRMS):
- 4-slot decision scaffold (Eligibility → Capability → Buyer → Timeline)
- Bid manager tone (not AI similarity explanations)
- Concrete capability naming (not vague "alignment" language)
- Uncertainty admission (builds trust)

RELIABILITY FEATURES:
- Batch processing with progress tracking
- Timeout + exponential backoff retry
- Validation + repair for missing contracts
- Fallback scoring on failures
"""

import logging
import json
import sys
import time
from typing import List, Dict, Optional
from openai import OpenAI
from app.core.config import settings
from app.models.contract import Contract
from app.models.company import CompanyProfile

logger = logging.getLogger(__name__)

class LLMReranker:
    """Re-rank contracts using LLM with bid/no-bid decision framing."""
    
    BATCH_SIZE = 10
    MAX_API_RETRIES = 3
    MAX_REPAIR_ATTEMPTS = 2
    API_TIMEOUT = 120.0
    REPAIR_TIMEOUT = 30.0
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    def rerank_contracts_for_firm(
        self,
        firm: CompanyProfile,
        contracts: List[Dict],
    ) -> Dict[str, Dict]:
        """
        Re-rank contracts using LLM batch processing.
        
        Args:
            firm: CompanyProfile with capabilities, certs, preferences
            contracts: List of {contract, scores, metadata}
        
        Returns:
            dict[qdrant_id] -> {
                'llm_score': 0-100,
                'llm_verdict': 'pursue|monitor|pass',
                'llm_reasons': ['...'],
                'llm_flags': ['...']
            }
        """
        start_time = time.time()
        total_contracts = len(contracts)
        total_batches = (total_contracts + self.BATCH_SIZE - 1) // self.BATCH_SIZE
        
        logger.info(f"🤖 LLM RE-RANKING START")
        logger.info(f"   🏢 Firm: {firm.company_name}")
        logger.info(f"   📊 Contracts: {total_contracts}")
        logger.info(f"   📦 Batches: {total_batches} × {self.BATCH_SIZE}")
        sys.stdout.flush()
        
        results = {}
        successful_batches = 0
        failed_batches = 0
        
        for i in range(0, len(contracts), self.BATCH_SIZE):
            batch_num = i // self.BATCH_SIZE + 1
            batch = contracts[i:i + self.BATCH_SIZE]
            batch_start = time.time()
            
            logger.info(f"")
            logger.info(f"📦 Batch {batch_num}/{total_batches} - {len(batch)} contracts")
            sys.stdout.flush()
            
            try:
                batch_results = self._process_batch(firm, batch, batch_num, total_batches)
                results.update(batch_results)
                successful_batches += 1
                
                batch_duration = time.time() - batch_start
                logger.info(f"   ✅ Complete in {batch_duration:.1f}s - {len(batch_results)} scored")
                sys.stdout.flush()
                
            except Exception as e:
                failed_batches += 1
                batch_duration = time.time() - batch_start
                
                logger.error(f"   ❌ FAILED after {batch_duration:.1f}s: {e}")
                sys.stdout.flush()
                
                # Fallback scoring
                for item in batch:
                    contract_id = item['contract'].qdrant_id
                    results[contract_id] = {
                        'llm_score': 50,
                        'llm_verdict': 'monitor',
                        'llm_reasons': ['LLM scoring unavailable - batch processing failed'],
                        'llm_flags': ['llm_error']
                    }
                
                logger.info(f"   ⚠️  Fallback scores assigned to {len(batch)} contracts")
                sys.stdout.flush()
        
        total_duration = time.time() - start_time
        
        logger.info(f"")
        logger.info(f"🎯 LLM RE-RANKING COMPLETE")
        logger.info(f"   ⏱️  {total_duration/60:.1f}m ({total_duration:.0f}s)")
        logger.info(f"   ✅ Success: {successful_batches}/{total_batches}")
        logger.info(f"   ❌ Failed: {failed_batches}/{total_batches}")
        logger.info(f"   📊 Scored: {len(results)}/{total_contracts}")
        sys.stdout.flush()
        
        return results
    
    def _process_batch(
        self,
        firm: CompanyProfile,
        batch: List[Dict],
        batch_num: int,
        total_batches: int
    ) -> Dict[str, Dict]:
        """Process one batch with validation + repair."""
        
        logger.info(f"   🔨 Building prompt...")
        sys.stdout.flush()
        
        prompt = self._build_prompt(firm, batch)
        expected_ids = [item['contract'].qdrant_id for item in batch]
        
        # API call with retry
        response = None
        for attempt in range(self.MAX_API_RETRIES):
            try:
                api_start = time.time()
                logger.info(f"   🌐 API call {attempt + 1}/{self.MAX_API_RETRIES}...")
                sys.stdout.flush()
                
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": self._get_system_prompt()},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    timeout=self.API_TIMEOUT
                )
                
                api_duration = time.time() - api_start
                logger.info(f"   ✅ API success in {api_duration:.1f}s")
                sys.stdout.flush()
                break
                
            except Exception as e:
                api_duration = time.time() - api_start
                logger.error(f"   ❌ Attempt {attempt + 1} failed ({api_duration:.1f}s): {e}")
                sys.stdout.flush()
                
                if attempt < self.MAX_API_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.info(f"   ⏳ Retry in {wait}s...")
                    sys.stdout.flush()
                    time.sleep(wait)
                else:
                    logger.error(f"   💥 All attempts failed")
                    sys.stdout.flush()
                    raise
        
        # Parse JSON
        logger.info(f"   📝 Parsing response...")
        sys.stdout.flush()
        
        raw_json = response.choices[0].message.content
        parsed = json.loads(raw_json)
        
        results = {}
        for item in parsed.get('results', []):
            contract_id = item['contract_id']
            results[contract_id] = {
                'llm_score': item['score'],
                'llm_verdict': item['verdict'],
                'llm_reasons': item['reasons'],
                'llm_flags': item.get('flags', [])
            }
        
        logger.info(f"   📊 Parsed {len(results)} scores")
        sys.stdout.flush()
        
        # Validation
        missing_ids = set(expected_ids) - set(results.keys())
        
        if missing_ids:
            logger.warning(f"   ⚠️  {len(missing_ids)} contracts missing - repairing...")
            sys.stdout.flush()
            
            repair_results = self._repair_missing_contracts(firm, batch, missing_ids)
            results.update(repair_results)
            
            logger.info(f"   🔧 After repair: {len(results)}/{len(expected_ids)} scored")
            sys.stdout.flush()
        
        return results
    
    def _repair_missing_contracts(
        self,
        firm: CompanyProfile,
        batch: List[Dict],
        missing_ids: set
    ) -> Dict[str, Dict]:
        """Repair pass for omitted contracts."""
        
        missing_contracts = [
            item for item in batch 
            if item['contract'].qdrant_id in missing_ids
        ]
        
        if not missing_contracts:
            return {}
        
        logger.info(f"   🔧 REPAIR: {len(missing_contracts)} contracts")
        sys.stdout.flush()
        
        for attempt in range(self.MAX_REPAIR_ATTEMPTS):
            try:
                repair_start = time.time()
                logger.info(f"      🔄 Attempt {attempt + 1}/{self.MAX_REPAIR_ATTEMPTS}")
                sys.stdout.flush()
                
                repair_prompt = self._build_repair_prompt(firm, missing_contracts)
                
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Score the missing contracts. Use bid/no-bid decision framing."},
                        {"role": "user", "content": repair_prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    timeout=self.REPAIR_TIMEOUT
                )
                
                repair_duration = time.time() - repair_start
                logger.info(f"      ✅ Repair API in {repair_duration:.1f}s")
                sys.stdout.flush()
                
                raw_json = response.choices[0].message.content
                parsed = json.loads(raw_json)
                
                repair_results = {}
                for item in parsed.get('results', []):
                    contract_id = item['contract_id']
                    repair_results[contract_id] = {
                        'llm_score': item['score'],
                        'llm_verdict': item['verdict'],
                        'llm_reasons': item['reasons'],
                        'llm_flags': item.get('flags', [])
                    }
                
                still_missing = missing_ids - set(repair_results.keys())
                
                if still_missing:
                    logger.warning(f"      ⚠️  Still missing {len(still_missing)}")
                    sys.stdout.flush()
                    
                    if attempt < self.MAX_REPAIR_ATTEMPTS - 1:
                        continue
                    else:
                        # Final fallback
                        for mid in still_missing:
                            repair_results[mid] = self._fallback_score()
                
                logger.info(f"      ✅ Repaired {len(repair_results)}/{len(missing_ids)}")
                sys.stdout.flush()
                return repair_results
                
            except Exception as e:
                repair_duration = time.time() - repair_start
                logger.error(f"      ❌ Attempt {attempt + 1} failed ({repair_duration:.1f}s): {e}")
                sys.stdout.flush()
                
                if attempt < self.MAX_REPAIR_ATTEMPTS - 1:
                    continue
                
                # Total failure fallback
                logger.error(f"      💥 All repairs failed - using fallback")
                sys.stdout.flush()
                
                return {mid: self._fallback_score() for mid in missing_ids}
        
        return {mid: self._fallback_score() for mid in missing_ids}
    
    def _fallback_score(self) -> Dict:
        """Neutral fallback when LLM fails."""
        return {
            'llm_score': 50,
            'llm_verdict': 'monitor',
            'llm_reasons': ['LLM scoring unavailable - manual review recommended'],
            'llm_flags': ['llm_unavailable']
        }
    
    def _get_system_prompt(self) -> str:
        """System prompt with bid manager persona and decision framing."""
        return """You are a senior bid manager for federal systems integrators and IT services firms.

Your job: Help firms triage opportunities during weekly pipeline reviews.

CRITICAL INSTRUCTION: Your "reasons" must sound like internal bid/no-bid checklist language — NOT generic AI similarity statements.

=== 4-SLOT DECISION SCAFFOLD ===

Use this structure for EVERY contract's reasons array:

1. ELIGIBILITY GATE
   Ask: "Is there an obvious blocker?"
   
   If safe:
   → "No obvious eligibility blockers detected"
   → "Full and open competition — no set-aside restrictions"
   
   If uncertain:
   → "Requires SDVOSB certification — verify eligibility"
   → "Set-aside designation unclear — manual review needed"

2. CAPABILITY ALIGNMENT
   Ask: "Does this map to what they actually do?"
   
   Be specific:
   → "Strong scope fit with your IT modernization and cloud migration capabilities"
   → "Core requirement matches your cybersecurity and systems integration services"
   → "Partial alignment with your data analytics practice — consulting scope may stretch"
   
   Avoid vague:
   ✗ "Aligns with your profile"
   ✗ "High similarity detected"

3. BUYER RELEVANCE
   Ask: "Is this a buyer they understand?"
   
   Use grounded language:
   → "Buying agency matches your typical federal customer profile"
   → "DoD buyer aligns with your past contract wins"
   → "Agency outside recent focus — requires strategic consideration"
   → "Civilian agency procurement — different from your DoD focus"

4. TIMELINE SANITY
   Ask: "Is this a scramble or manageable?"
   
   Be practical:
   → "Standard 45-day response window — manageable timeline"
   → "Timeline consistent with rapid-response bids"
   → "Compressed 15-day deadline — requires immediate mobilization"
   → "Extended timeline — may indicate low urgency"

=== SCORING RUBRIC (0-100) ===

- 45% Capability fit (technical requirements match firm's core services)
- 25% Eligibility (set-aside compatibility, certifications, vehicle access)
- 15% Buyer similarity (agency matches past wins/preferences)
- 15% Practicality (timeline, scope clarity, value band)

Downgrade for:
- Domain mismatch (e.g., "security" = guards when firm does cyber)
- Irrelevant NAICS/industry codes
- Vague/missing scope descriptions
- Set-aside certification mismatch
- Unrealistic timelines or unclear deadlines
- Value band way outside firm's typical range

=== VERDICT GUIDANCE ===

- pursue (75-100): Strong fit, few barriers, clear win path
- monitor (50-74): Decent fit but has complications/uncertainties
- pass (0-49): Poor fit, major blockers, or resource mismatch

=== TONE ===

Professional. Concise. Decision-support.

Sound like a senior bid manager briefing their BD team.

Never use:
- Marketing language
- ML/AI jargon ("embeddings", "semantic similarity", "confidence scores")
- Overly enthusiastic phrasing

=== OUTPUT ===

Strict JSON only. Include ALL contracts in results array."""

    def _build_prompt(self, firm: CompanyProfile, batch: List[Dict]) -> str:
        """Build user prompt with firm context + contracts + examples."""
        
        firm_summary = self._build_firm_summary(firm)
        batch_ids = [item['contract'].qdrant_id for item in batch]
        
        contract_list = []
        for idx, item in enumerate(batch):
            contract = item['contract']
            matched_cap = item['scores'].get('matched_capabilities', [None])[0]
            contract_list.append(self._format_contract(contract, idx, matched_cap))
        
        prompt = f"""# Firm Profile

{firm_summary}

# Contract IDs to Score (ALL {len(batch)} required)

{', '.join(batch_ids)}

# Contracts

{chr(10).join(contract_list)}

# Your Task

Score each contract 0-100 using the scoring rubric from your system prompt.

Provide verdict: pursue | monitor | pass

Generate 4 reasons using the decision scaffold:

**Slot 1 - Eligibility:**
✓ "No obvious eligibility blockers detected"
✓ "Full and open competition — no set-aside"
✗ "Requires 8(a) certification — verify eligibility"

**Slot 2 - Capability:**
✓ "Strong scope fit with your IT modernization and systems integration capabilities"
✓ "Core requirement matches your cloud services and DevSecOps practice"
✗ "Partial capability match — consulting scope may be a stretch"

**Slot 3 - Buyer:**
✓ "Buying agency (DoD) matches your existing customer base"
✓ "Agency aligns with your federal contracting profile"
✗ "Civilian agency — outside your recent DoD focus"

**Slot 4 - Timeline:**
✓ "Standard 30-day response window"
✓ "Timeline consistent with rapid-response bids"
✗ "Compressed 10-day deadline — immediate mobilization required"

=== BAD EXAMPLES (DO NOT USE) ===

❌ "High semantic similarity to past wins"
❌ "Strong embeddings alignment detected"
❌ "AI confidence score: 0.87"
❌ "This matches your profile based on ML analysis"

=== GOOD EXAMPLES (USE THIS STYLE) ===

✅ "No set-aside restrictions — open competition"
✅ "Strong alignment with your IT modernization and cloud migration capabilities"
✅ "Buying agency (VA) matches your existing federal customer profile"
✅ "Standard 45-day response window — manageable timeline"

=== Output Format ===

{{
  "results": [
    {{
      "contract_id": "exact_qdrant_id_from_list_above",
      "score": 0-100,
      "verdict": "pursue|monitor|pass",
      "reasons": [
        "Eligibility slot reason",
        "Capability slot reason",
        "Buyer slot reason",
        "Timeline slot reason"
      ],
      "flags": ["tight_deadline", "unclear_scope", "wrong_domain", "missing_cert"]
    }}
  ]
}}

CRITICAL: Include all {len(batch)} contracts. Use exact IDs from the list above."""
        
        return prompt
    
    def _build_repair_prompt(self, firm: CompanyProfile, missing_contracts: List[Dict]) -> str:
        """Minimal repair prompt for omitted contracts."""
        
        firm_name = firm.company_name
        
        contract_lines = []
        for item in missing_contracts:
            contract = item['contract']
            contract_lines.append(
                f"ID: {contract.qdrant_id}\n"
                f"Title: {contract.title[:120] if contract.title else 'N/A'}\n"
                f"Agency: {contract.buyer_name or 'N/A'}\n"
                f"Set-Aside: {contract.set_aside or 'Full & Open'}\n"
                f"---"
            )
        
        return f"""You omitted these contracts. Score them now.

Firm: {firm_name}

Missing Contracts ({len(missing_contracts)}):

{chr(10).join(contract_lines)}

Return JSON with ONLY these {len(missing_contracts)} contracts using the 4-slot decision scaffold:

{{
  "results": [
    {{
      "contract_id": "...",
      "score": 0-100,
      "verdict": "pursue|monitor|pass",
      "reasons": ["eligibility", "capability", "buyer", "timeline"],
      "flags": []
    }}
  ]
}}"""
    
    def _build_firm_summary(self, firm: CompanyProfile) -> str:
        """Build concise firm summary for prompt context."""
        
        # Certifications
        certs = []
        if firm.sdvosb_certified:
            certs.append("SDVOSB")
        if firm.eight_a_certified:
            certs.append("8(a)")
        if firm.wosb_certified:
            certs.append("WOSB")
        if firm.hubzone_certified:
            certs.append("HUBZone")
        if firm.sba_certified:
            certs.append("Small Business")
        cert_text = ", ".join(certs) if certs else "None listed"
        
        # NAICS
        naics_text = ", ".join(firm.naics_codes[:3]) if firm.naics_codes else "Not specified"
        
        # Core capabilities
        cap_lines = []
        if firm.capabilities:
            for cap in firm.capabilities[:5]:
                if cap.capability_text:
                    cap_lines.append(f"  • {cap.capability_text[:120]}")
        cap_text = "\n".join(cap_lines) if cap_lines else "  (Not specified)"
        
        # Preferred agencies
        pref_agencies = ""
        if firm.search_preference and firm.search_preference.preferred_agencies:
            agencies = firm.search_preference.preferred_agencies[:3]
            pref_agencies = f"\nPreferred Agencies: {', '.join(agencies)}"
        
        summary = f"""**Company:** {firm.company_name}

**Certifications:** {cert_text}

**Primary NAICS:** {naics_text}{pref_agencies}

**Core Capabilities:**
{cap_text}"""
        
        return summary[:900]  # Hard limit
    
    def _format_contract(self, contract: Contract, idx: int, matched_capability: Optional[str] = None) -> str:
        """Format contract for prompt (decision-relevant fields only)."""
        
        desc = (contract.description or "No description")[:250]
        
        # Value
        if contract.contract_value:
            try:
                value_str = f"${contract.contract_value:,.0f}"
            except (ValueError, TypeError):
                value_str = "Not disclosed"
        else:
            value_str = "Not disclosed"
        
        # Deadline
        closes_str = str(contract.closing_date) if contract.closing_date else "Not specified"
        
        # Top matched capability
        matched_cap_line = ""
        if matched_capability:
            matched_cap_line = f"**Top Capability Match:** {matched_capability[:140]}\n"
        
        return f"""## Contract {idx + 1}

**ID:** {contract.qdrant_id}
**Notice ID:** {contract.notice_id}
**Title:** {contract.title[:160] if contract.title else 'Untitled'}

**Agency:** {contract.buyer_name or 'Not specified'}
**Set-Aside:** {contract.set_aside or 'Full & Open'}
**NAICS:** {contract.naics_code or 'N/A'}
**Region:** {contract.region or 'N/A'}

**Value:** {value_str}
**Closes:** {closes_str}

{matched_cap_line}**Description:** {desc}...

---"""