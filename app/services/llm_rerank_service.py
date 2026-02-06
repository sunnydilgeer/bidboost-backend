"""
LLM Re-Ranking Service - Phase 1.5

Batch re-ranks semantic candidates using GPT-4o-mini for better judgment.
Scores contracts on capability fit, eligibility, and practicality.

FIXES APPLIED:
- Use qdrant_id (not notice_id) as contract identifier
- Include matched_capabilities in prompt for better context
- Validation + repair pass for missing contracts
- Timeout + retry limits to prevent hanging
- Verbose logging with timestamps
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
    """Re-rank contracts using LLM for nuanced assessment."""
    
    BATCH_SIZE = 10  # ✅ REDUCED for faster response
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    def rerank_contracts_for_firm(
        self,
        firm: CompanyProfile,
        contracts: List[Dict],  # List of {contract, scores, metadata}
    ) -> Dict[str, Dict]:
        """
        Re-rank contracts using LLM batch processing.
        
        Returns: dict[qdrant_id] -> {
            'llm_score': 0-100,
            'llm_verdict': 'pursue|monitor|pass',
            'llm_reasons': ['...'],
            'llm_flags': ['...']
        }
        """
        start_time = time.time()
        total_contracts = len(contracts)
        total_batches = (total_contracts + self.BATCH_SIZE - 1) // self.BATCH_SIZE
        
        logger.info(f"🤖 PHASE 1.5 START: LLM re-ranking {total_contracts} contracts")
        logger.info(f"   📊 Configuration: {total_batches} batches × {self.BATCH_SIZE} contracts/batch")
        logger.info(f"   🏢 Firm: {firm.company_name}")
        sys.stdout.flush()
        
        results = {}
        successful_batches = 0
        failed_batches = 0
        
        # Process in batches
        for i in range(0, len(contracts), self.BATCH_SIZE):
            batch_num = i // self.BATCH_SIZE + 1
            batch = contracts[i:i + self.BATCH_SIZE]
            batch_start = time.time()
            
            logger.info(f"")
            logger.info(f"📦 Batch {batch_num}/{total_batches} - Processing {len(batch)} contracts...")
            sys.stdout.flush()
            
            try:
                batch_results = self._process_batch(firm, batch, batch_num, total_batches)
                results.update(batch_results)
                successful_batches += 1
                
                batch_duration = time.time() - batch_start
                logger.info(f"✅ Batch {batch_num}/{total_batches} complete in {batch_duration:.1f}s - {len(batch_results)} contracts scored")
                sys.stdout.flush()
                
            except Exception as e:
                failed_batches += 1
                batch_duration = time.time() - batch_start
                
                logger.error(f"❌ Batch {batch_num}/{total_batches} FAILED after {batch_duration:.1f}s: {e}")
                sys.stdout.flush()
                
                # Fallback: assign neutral scores
                for item in batch:
                    contract_id = item['contract'].qdrant_id
                    results[contract_id] = {
                        'llm_score': 50,
                        'llm_verdict': 'monitor',
                        'llm_reasons': ['LLM scoring unavailable - batch failed'],
                        'llm_flags': ['llm_error']
                    }
                
                logger.info(f"   ⚠️  Assigned fallback scores to {len(batch)} contracts")
                sys.stdout.flush()
        
        total_duration = time.time() - start_time
        
        logger.info(f"")
        logger.info(f"🎯 PHASE 1.5 COMPLETE")
        logger.info(f"   ⏱️  Total time: {total_duration/60:.1f} minutes ({total_duration:.0f}s)")
        logger.info(f"   ✅ Successful batches: {successful_batches}/{total_batches}")
        logger.info(f"   ❌ Failed batches: {failed_batches}/{total_batches}")
        logger.info(f"   📊 Contracts scored: {len(results)}/{total_contracts}")
        logger.info(f"   ⚡ Avg time per batch: {total_duration/total_batches:.1f}s")
        sys.stdout.flush()
        
        return results
    
    def _process_batch(
        self,
        firm: CompanyProfile,
        batch: List[Dict],
        batch_num: int,
        total_batches: int
    ) -> Dict[str, Dict]:
        """Process one batch of contracts with validation + repair."""
        
        # Build prompt
        logger.info(f"   🔨 Building prompt for batch {batch_num}...")
        sys.stdout.flush()
        prompt = self._build_prompt(firm, batch)
        
        # Get expected IDs for validation
        expected_ids = [item['contract'].qdrant_id for item in batch]
        logger.info(f"   📋 Expected {len(expected_ids)} contract IDs")
        sys.stdout.flush()
        
        # Call OpenAI with retry logic
        max_retries = 3
        response = None
        
        for attempt in range(max_retries):
            try:
                api_start = time.time()
                logger.info(f"   🌐 API call attempt {attempt + 1}/{max_retries} (timeout: 120s)...")
                sys.stdout.flush()
                
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": self._get_system_prompt()},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    timeout=120.0
                )
                
                api_duration = time.time() - api_start
                logger.info(f"   ✅ API call succeeded in {api_duration:.1f}s")
                sys.stdout.flush()
                break
                
            except Exception as e:
                api_duration = time.time() - api_start
                logger.error(f"   ❌ Attempt {attempt + 1} failed after {api_duration:.1f}s: {e}")
                sys.stdout.flush()
                
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.info(f"   ⏳ Retrying in {wait_time}s...")
                    sys.stdout.flush()
                    time.sleep(wait_time)
                else:
                    logger.error(f"   💥 All {max_retries} attempts failed - giving up on batch {batch_num}")
                    sys.stdout.flush()
                    raise
        
        # Parse response
        logger.info(f"   📝 Parsing JSON response...")
        sys.stdout.flush()
        
        raw_json = response.choices[0].message.content
        parsed = json.loads(raw_json)
        
        # Convert to dict keyed by qdrant_id
        results = {}
        for item in parsed.get('results', []):
            contract_id = item['contract_id']
            results[contract_id] = {
                'llm_score': item['score'],
                'llm_verdict': item['verdict'],
                'llm_reasons': item['reasons'],
                'llm_flags': item.get('flags', [])
            }
        
        logger.info(f"   📊 Parsed {len(results)} contract scores from LLM")
        sys.stdout.flush()
        
        # ✅ VALIDATION: Check for missing contracts
        missing_ids = set(expected_ids) - set(results.keys())
        
        if missing_ids:
            logger.warning(f"   ⚠️  LLM omitted {len(missing_ids)} contracts - attempting repair...")
            sys.stdout.flush()
            
            repair_results = self._repair_missing_contracts(firm, batch, missing_ids, batch_num)
            results.update(repair_results)
            
            logger.info(f"   🔧 After repair: {len(results)}/{len(expected_ids)} contracts have scores")
            sys.stdout.flush()
        
        return results
    
    def _repair_missing_contracts(
        self,
        firm: CompanyProfile,
        batch: List[Dict],
        missing_ids: set,
        batch_num: int,
        max_attempts: int = 2
    ) -> Dict[str, Dict]:
        """
        Repair pass for contracts the LLM omitted.
        Retries up to max_attempts with timeout.
        """
        missing_contracts = [
            item for item in batch 
            if item['contract'].qdrant_id in missing_ids
        ]
        
        if not missing_contracts:
            return {}
        
        logger.info(f"   🔧 REPAIR: Attempting to score {len(missing_contracts)} missing contracts")
        sys.stdout.flush()
        
        # ✅ TRY REPAIR WITH TIMEOUT AND RETRIES
        for attempt in range(max_attempts):
            try:
                repair_start = time.time()
                logger.info(f"      🔄 Repair attempt {attempt + 1}/{max_attempts}...")
                sys.stdout.flush()
                
                # Build minimal repair prompt
                repair_prompt = f"""You previously omitted these contracts. Score them now.

Firm: {firm.company_name}

Missing Contracts:
{chr(10).join([f"ID: {item['contract'].qdrant_id}, Title: {item['contract'].title[:100]}" for item in missing_contracts])}

Return JSON with ONLY these {len(missing_contracts)} contracts:
{{
  "results": [
    {{"contract_id": "...", "score": 0-100, "verdict": "pursue|monitor|pass", "reasons": ["..."], "flags": []}}
  ]
}}"""
                
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Score the missing contracts in JSON."},
                        {"role": "user", "content": repair_prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    timeout=30.0
                )
                
                repair_duration = time.time() - repair_start
                logger.info(f"      ✅ Repair API call succeeded in {repair_duration:.1f}s")
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
                
                # ✅ CHECK IF REPAIR WAS SUCCESSFUL
                still_missing = missing_ids - set(repair_results.keys())
                
                if still_missing:
                    logger.warning(f"      ⚠️  Repair still missing {len(still_missing)} contracts")
                    sys.stdout.flush()
                    
                    if attempt < max_attempts - 1:
                        logger.info(f"      🔄 Will retry repair...")
                        sys.stdout.flush()
                        continue
                    else:
                        # Give up, use fallback for still-missing
                        logger.warning(f"      ⚠️  Using fallback scores for {len(still_missing)} contracts")
                        sys.stdout.flush()
                        
                        for mid in still_missing:
                            repair_results[mid] = {
                                'llm_score': 50,
                                'llm_verdict': 'monitor',
                                'llm_reasons': ['LLM scoring unavailable after retries'],
                                'llm_flags': ['repair_failed']
                            }
                
                logger.info(f"      ✅ Repair recovered {len(repair_results)}/{len(missing_ids)} contracts")
                sys.stdout.flush()
                return repair_results
                
            except Exception as e:
                repair_duration = time.time() - repair_start
                logger.error(f"      ❌ Repair attempt {attempt + 1} failed after {repair_duration:.1f}s: {e}")
                sys.stdout.flush()
                
                if attempt < max_attempts - 1:
                    logger.info(f"      ⏳ Retrying repair...")
                    sys.stdout.flush()
                    continue
                
                # Final fallback - return neutral scores for ALL missing
                logger.error(f"      💥 All repair attempts failed - using fallback for {len(missing_ids)} contracts")
                sys.stdout.flush()
                
                return {
                    mid: {
                        'llm_score': 50,
                        'llm_verdict': 'monitor',
                        'llm_reasons': ['LLM scoring unavailable - repair failed'],
                        'llm_flags': ['repair_error']
                    }
                    for mid in missing_ids
                }
        
        # Should never reach here
        return {
            mid: {
                'llm_score': 50,
                'llm_verdict': 'monitor',
                'llm_reasons': ['LLM scoring unavailable'],
                'llm_flags': ['repair_timeout']
            }
            for mid in missing_ids
        }
    
    def _get_system_prompt(self) -> str:
        return """You are a government contracting bid analyst. Score contracts based on fit and win-likelihood.

Scoring Rubric (0-100):
- 45% Capability fit (technical requirements match)
- 25% Eligibility (set-aside + certifications)
- 15% Buyer similarity (agency preference/past experience)
- 15% Practicality (timeline, scope clarity, value band)

Downgrade for:
- "Security" meaning guards vs cyber (domain mismatch)
- Irrelevant NAICS/industry
- Missing/weak description
- Set-aside certification mismatch
- Unrealistic timelines

Output strict JSON only. Include ALL contracts in results."""
    
    def _build_prompt(self, firm: CompanyProfile, batch: List[Dict]) -> str:
        """Build the user prompt with firm + contracts."""
        
        # Firm summary (truncated to 300 words)
        firm_summary = self._build_firm_summary(firm)
        
        # Get all batch IDs upfront (helps model compliance)
        batch_ids = [item['contract'].qdrant_id for item in batch]
        
        # Contract list
        contract_list = []
        for idx, item in enumerate(batch):
            contract = item['contract']
            matched_cap = item['scores'].get('matched_capabilities', [None])[0]
            contract_list.append(self._format_contract(contract, idx, matched_cap))
        
        prompt = f"""# Firm Profile

{firm_summary}

# Batch IDs (you must score ALL of these):
{', '.join(batch_ids)}

# Contracts to Score ({len(batch)} total)

{chr(10).join(contract_list)}

# Task

Score each contract 0-100 and provide verdict (pursue/monitor/pass).

Output JSON:
{{
  "results": [
    {{
      "contract_id": "string",
      "score": 0-100,
      "verdict": "pursue|monitor|pass",
      "reasons": ["...", "...", "..."],
      "flags": ["missing_cert", "wrong_domain", "tight_deadline", "unclear_scope"]
    }}
  ]
}}

CRITICAL: Include all {len(batch)} contracts in results. Use the exact IDs from the Batch IDs list above."""
        
        return prompt
    
    def _build_firm_summary(self, firm: CompanyProfile) -> str:
        """Build concise firm summary (max 300 words)."""
        
        # Core capabilities (top 5)
        cap_text = ""
        if firm.capabilities:
            caps = [c.capability_text for c in firm.capabilities[:5] if c.capability_text]
            cap_text = "- " + "\n- ".join(caps[:3])  # Top 3 only
        
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
        
        cert_text = ", ".join(certs) if certs else "None"
        
        # NAICS
        naics_text = ", ".join(firm.naics_codes[:3]) if firm.naics_codes else "Not specified"
        
        # Preferred agencies
        pref_agencies = ""
        if firm.search_preference and firm.search_preference.preferred_agencies:
            pref_agencies = ", ".join(firm.search_preference.preferred_agencies[:3])
        
        summary = f"""Company: {firm.company_name}

Certifications: {cert_text}
Primary NAICS: {naics_text}
{f"Preferred Agencies: {pref_agencies}" if pref_agencies else ""}

Core Capabilities:
{cap_text}"""
        
        return summary[:800]  # Hard limit
    
    def _format_contract(self, contract: Contract, idx: int, matched_capability: Optional[str] = None) -> str:
        """Format single contract for prompt (truncated)."""
        
        # Truncate description
        desc = (contract.description or "")[:200]
        
        # Format contract value safely
        if contract.contract_value:
            try:
                value_str = f"${contract.contract_value:,.0f}"
            except (ValueError, TypeError):
                value_str = "N/A"
        else:
            value_str = "N/A"
        
        # Format closing date safely
        closes_str = str(contract.closing_date) if contract.closing_date else "N/A"
        
        # ✅ INCLUDE MATCHED CAPABILITY
        matched_cap_line = f"Top Matched Capability: {matched_capability[:150]}" if matched_capability else ""
        
        return f"""## Contract {idx + 1}
ID: {contract.qdrant_id}
Notice ID: {contract.notice_id}
Title: {contract.title[:160] if contract.title else 'N/A'}
Agency: {contract.buyer_name or 'N/A'}
Description: {desc}...
{matched_cap_line}
NAICS: {contract.naics_code or 'N/A'}
Set-Aside: {contract.set_aside or 'Full & Open'}
Region: {contract.region or 'N/A'}
Value: {value_str}
Closes: {closes_str}
---"""
