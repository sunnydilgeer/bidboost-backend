"""
Background Job: Pre-compute Contract Matches - THREE-PHASE STRATEGY

Phase 1: Multi-query semantic matching with diversity boost (3-7 min)
Phase 1.5: LLM re-ranking for quality (2-4 min) 
Phase 2: Batched strategic intelligence enrichment (15-20 min)

Runs nightly to cache top 500 matches per company in PostgreSQL

✨ NEW: DIVERSITY SCORING
- Contracts matching multiple capabilities get boosted
- Prevents single capability from dominating results
- 5% boost per additional capability (max 15%)

FIXES APPLIED:
- Use qdrant_id (Pinecone vector ID) for LLM result keying, not notice_id
- Fixed score normalization: equal weight semantic + LLM (both 0-100 scale)
- PSC-aware strategic intelligence for contract-specific data
- Multi-capability diversity boost
- Comprehensive logging with progress tracking
- Batched Pinecone vector fetching (100 at a time to avoid URI length errors)
"""

import logging
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import delete
from datetime import datetime, timezone
from collections import defaultdict
import json
import time
import sys

from app.database import SessionLocal
from app.models.company import CompanyProfile, CachedContractMatch
from app.models.contract import Contract
from app.services.match_scoring import ContractMatchScorer
from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings

logger = logging.getLogger(__name__)

class MatchCacheService:
    """
    Service for pre-computing and caching contract matches.
    Runs as a background job to speed up dashboard loading.
    
    THREE-PHASE CACHING STRATEGY:
    Phase 1: Multi-query semantic matching with diversity boost (3-7 min)
    Phase 1.5: LLM re-ranking for better judgment (2-4 min)
    Phase 2: Strategic intelligence via PSC-aware batched queries (15-20 min)
    """
    
    def __init__(self):
        self.db: Session = None
        self.pinecone = None
        self.scorer = None
    
    def run_cache_update(self, firm_ids: List[str] = None):
        """
        Update match cache for specified firms (or all firms if None).
        
        Args:
            firm_ids: List of firm IDs to update, or None for all firms
        """
        try:
            self.db = SessionLocal()
            self.pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
            self.scorer = ContractMatchScorer(self.db, self.pinecone.index)
            
            # Get firms to update
            if firm_ids:
                firms = self.db.query(CompanyProfile).filter(
                    CompanyProfile.firm_id.in_(firm_ids)
                ).all()
            else:
                firms = self.db.query(CompanyProfile).all()
            
            logger.info(f"🔄 Starting cache update for {len(firms)} firms...")
            sys.stdout.flush()
            
            for firm in firms:
                try:
                    # PHASE 1: Multi-query semantic matching with diversity boost (3-7 min)
                    self._update_firm_cache(firm)
                    
                    # PHASE 2: Strategic intelligence enrichment (15-20 min)
                    self.enrich_cached_matches_batched(firm.firm_id)
                    
                except Exception as e:
                    logger.error(f"Failed to update cache for firm {firm.firm_id}: {e}")
                    continue
            
            logger.info(f"✅ Cache update complete for {len(firms)} firms")
            sys.stdout.flush()
            
        except Exception as e:
            logger.error(f"Cache update failed: {e}", exc_info=True)
        finally:
            if self.db:
                self.db.close()
    
    def _truncate_metadata(self, metadata: dict) -> dict:
        """
        Truncate fields that exceed database VARCHAR limits.
        Prevents StringDataRightTruncation errors during cache update.
        
        🚨 CRITICAL FIX: Without this, cache cron crashes on firm-ibmer
        and blocks all firms alphabetically after it from getting fresh matches.
        """
        max_lengths = {
            'office': 255,
            'naics_code': 255,
            'psc_code': 255,
            'set_aside': 255,
            'contact_name': 255,
            'contact_email': 255,
            'contact_phone': 50,
            'city': 100,
        }
        
        truncated_fields = []
        
        for field, max_len in max_lengths.items():
            if field in metadata and metadata[field]:
                original_value = str(metadata[field])
                if len(original_value) > max_len:
                    metadata[field] = original_value[:max_len]
                    truncated_fields.append(f"{field}({len(original_value)}→{max_len})")
        
        if truncated_fields:
            logger.warning(
                f"Truncated fields for contract {metadata.get('notice_id', 'unknown')}: "
                f"{', '.join(truncated_fields)}"
            )
        
        return metadata
    
    def _serialize_strategic_intel(self, data: dict) -> str:
        """
        Serialize strategic intelligence data to JSON string for database storage.
        
        Handles:
        - incumbent_data: Dict with incumbent info
        - pricing_benchmarks: Dict with avg/min/max awards + granularity
        - competition_stats: Dict with avg offers, set-aside distribution + granularity
        """
        if data is None:
            return None
        
        try:
            return json.dumps(data)
        except Exception as e:
            logger.error(f"Error serializing strategic intelligence: {e}")
            return None
    
    def _update_firm_cache(self, firm: CompanyProfile):
        """
        PHASE 1: Multi-query semantic matching with diversity boost + LLM re-ranking (5-10 min).
        
        ✨ NEW DIVERSITY SCORING:
        1. Query Pinecone with ALL capability vectors (not just first)
        2. Track ALL capabilities that match each contract
        3. Apply diversity boost: +5% per additional capability (max +15%)
        4. Merge and dedupe results by contract_id
        5. Score top 1000 candidates
        6. LLM re-rank top 500 with nuanced judgment
        7. Save with enrichment_status='pending' for Phase 2
        """
        phase1_start = time.time()
        
        logger.info(f"")
        logger.info(f"{'='*80}")
        logger.info(f"⚡ PHASE 1: Multi-query matching for {firm.company_name} (firm_id: {firm.firm_id})")
        logger.info(f"{'='*80}")
        sys.stdout.flush()
        
        # Check if firm has capabilities
        if not firm.capabilities:
            logger.warning(f"Firm {firm.firm_id} has no capabilities - skipping")
            return
        
        # Pre-fetch capability vectors
        from app.services.capability_store_pinecone import get_capability_store
        cap_store = get_capability_store()
        
        capability_ids = [cap.qdrant_id for cap in firm.capabilities if cap.qdrant_id]
        if not capability_ids:
            logger.warning(f"Firm {firm.firm_id} has no capability vectors - skipping")
            return
        
        logger.info(f"📋 Fetching {len(capability_ids)} capability vectors...")
        sys.stdout.flush()
        
        capability_vectors = cap_store.get_capabilities_batch(capability_ids)
        logger.info(f"✅ Retrieved {len(capability_vectors)} capability vectors")
        sys.stdout.flush()
        
        # Pre-fetch past win vectors (if any)
        past_win_vectors = {}
        if firm.past_wins:
            from app.services.past_win_store_pinecone import get_past_win_store
            win_store = get_past_win_store()
            past_win_ids = [win.pinecone_id for win in firm.past_wins if win.pinecone_id]
            if past_win_ids:
                logger.info(f"📋 Fetching {len(past_win_ids)} past win vectors...")
                sys.stdout.flush()
                past_win_vectors = win_store.get_past_wins_batch(past_win_ids)
                logger.info(f"✅ Retrieved {len(past_win_vectors)} past win vectors")
                sys.stdout.flush()
        
        # ✅ MULTI-QUERY PINECONE WITH DIVERSITY TRACKING
        merged_results = {}  # contract_id -> {score, metadata, values, matched_capabilities, capability_scores}
        
        logger.info(f"")
        logger.info(f"🔍 Querying Pinecone with {len(capability_ids)} capability vectors...")
        sys.stdout.flush()
        
        for idx, cap_id in enumerate(capability_ids):
            cap_vector = capability_vectors.get(cap_id)
            if not cap_vector:
                logger.warning(f"No vector for capability {cap_id}, skipping")
                continue
            
            logger.info(f"   📡 Querying capability {idx+1}/{len(capability_ids)}...")
            sys.stdout.flush()
            
            # Query with this capability
            search_results = self.pinecone.index.query(
                vector=cap_vector,
                namespace="contracts",
                top_k=200,  # 200 per capability (tunable)
                include_metadata=True,
                include_values=True
            )
            
            # ✅ NEW: Track ALL capabilities that match each contract
            for result in search_results.matches:
                contract_id = result.id
                
                if contract_id not in merged_results:
                    merged_results[contract_id] = {
                        'score': result.score,
                        'metadata': result.metadata,
                        'values': result.values,
                        'matched_capabilities': [idx],  # ✅ Track which capabilities matched
                        'capability_scores': [result.score]  # ✅ Track all scores
                    }
                else:
                    # Already seen this contract - add this capability match
                    merged_results[contract_id]['matched_capabilities'].append(idx)
                    merged_results[contract_id]['capability_scores'].append(result.score)
                    
                    # Update max score if this one is higher
                    if result.score > merged_results[contract_id]['score']:
                        merged_results[contract_id]['score'] = result.score
        
        logger.info(f"✅ Found {len(merged_results)} unique contracts across {len(capability_ids)} capabilities")
        sys.stdout.flush()
        
        # ✅ APPLY DIVERSITY BOOST: Contracts matching multiple capabilities get bonus
        multi_cap_count = 0
        for contract_id, data in merged_results.items():
            num_capabilities_matched = len(data['matched_capabilities'])
            base_score = data['score']
            
            # 5% boost per additional capability (capped at 15% total)
            diversity_boost = min((num_capabilities_matched - 1) * 0.05, 0.15)
            boosted_score = min(base_score + diversity_boost, 1.0)
            
            # Store both for transparency
            data['base_score'] = base_score
            data['diversity_boost'] = diversity_boost
            data['boosted_score'] = boosted_score
            data['num_capabilities_matched'] = num_capabilities_matched
            
            if num_capabilities_matched > 1:
                multi_cap_count += 1
        
        logger.info(
            f"📊 Diversity stats: "
            f"{multi_cap_count}/{len(merged_results)} contracts match 2+ capabilities "
            f"({multi_cap_count/len(merged_results)*100:.1f}%)"
        )
        sys.stdout.flush()
        
        # Convert to sorted list by BOOSTED score
        all_results = sorted(
            merged_results.items(),
            key=lambda x: x[1]['boosted_score'],  # ✅ Sort by boosted score
            reverse=True
        )[:1000]  # Keep top 1000 for scoring
        
        # Convert back to Pinecone-style result format
        class PineconeMatch:
            def __init__(self, contract_id, data):
                self.id = contract_id
                self.score = data['boosted_score']  # ✅ Use boosted score
                self.metadata = data['metadata']
                self.values = data['values']
                self.num_capabilities_matched = data['num_capabilities_matched']
                self.diversity_boost = data['diversity_boost']
        
        pinecone_matches = [PineconeMatch(cid, data) for cid, data in all_results]
        
        logger.info(f"🎯 Selected top {len(pinecone_matches)} contracts for scoring")
        sys.stdout.flush()
        
        # Pre-fetch contract vectors in BATCHES (Pinecone has URL length limits)
        contract_ids = [r.id for r in pinecone_matches if r.id]
        contract_vectors = {}
        
        if contract_ids:
            try:
                FETCH_BATCH_SIZE = 100  # Fetch 100 vectors at a time
                total_batches = (len(contract_ids) + FETCH_BATCH_SIZE - 1) // FETCH_BATCH_SIZE
                
                logger.info(f"📋 Pre-fetching {len(contract_ids)} contract vectors in {total_batches} batches...")
                sys.stdout.flush()
                
                for i in range(0, len(contract_ids), FETCH_BATCH_SIZE):
                    batch_ids = contract_ids[i:i + FETCH_BATCH_SIZE]
                    batch_num = i // FETCH_BATCH_SIZE + 1
                    
                    try:
                        fetch_result = self.pinecone.index.fetch(
                            ids=batch_ids, 
                            namespace=settings.PINECONE_NAMESPACE
                        )
                        
                        for vec_id, vec_data in fetch_result.vectors.items():
                            contract_vectors[vec_id] = list(vec_data.values)
                        
                        if batch_num % 5 == 0:  # Log every 5 batches
                            logger.info(f"   ⚡ Fetched {len(contract_vectors)}/{len(contract_ids)} vectors...")
                            sys.stdout.flush()
                    except Exception as e:
                        logger.error(f"Failed to fetch batch {batch_num}: {e}")
                
                logger.info(f"✅ Pre-fetched {len(contract_vectors)} contract vectors")
                sys.stdout.flush()
            except Exception as e:
                logger.error(f"Failed to batch fetch contract vectors: {e}")
        
        # ✅ SCORE CONTRACTS WITH PROGRESS LOGGING
        logger.info(f"")
        logger.info(f"📊 Scoring {len(pinecone_matches)} contracts...")
        logger.info(f"   💾 Capability vectors: {len(capability_vectors)}")
        logger.info(f"   💾 Contract vectors: {len(contract_vectors)}")
        logger.info(f"   💾 Past win vectors: {len(past_win_vectors)}")
        sys.stdout.flush()
        
        scoring_start = time.time()
        processed_count = 0
        scored_matches = []
        
        for result in pinecone_matches:
            if not result.values or len(result.values) != 768:
                logger.warning(f"Skipping contract {result.id} - invalid vector (length: {len(result.values) if result.values else 0})")
                continue
            
            # Convert Pinecone result to Contract object
            metadata = result.metadata
            contract = Contract(
                notice_id=metadata.get("notice_id", ""),
                title=metadata.get("title", ""),
                buyer_name=metadata.get("agency", ""),
                description=metadata.get("description", ""),
                contract_value=metadata.get("contract_value"),
                region=metadata.get("state"),
                qdrant_id=result.id,  # ← Pinecone vector ID
                naics_code=metadata.get("naics_code"),
                naics_name=metadata.get("naics_name"),
                psc_code=metadata.get("psc_code"),
                set_aside=metadata.get("set_aside"),
                closing_date=metadata.get("response_deadline")
            )
            
            # ✅ Score with skip_strategic_intel=True (FAST MODE)
            scores = self.scorer.score_contract(
                contract=contract,
                firm_id=firm.firm_id,
                capability_vectors=capability_vectors,
                contract_vectors={result.id: result.values},
                past_win_vectors=past_win_vectors,
                skip_strategic_intel=True  # ← PHASE 1: SKIP STRATEGIC INTEL
            )
            
            if scores and scores["match_score"] >= 0.5:  # Only cache 50%+ matches
                scored_matches.append({
                    "contract": contract,
                    "scores": scores,
                    "metadata": metadata,
                    "num_capabilities_matched": result.num_capabilities_matched,
                    "diversity_boost": result.diversity_boost
                })
            
            # ✅ LOG PROGRESS EVERY 100 CONTRACTS
            processed_count += 1
            if processed_count % 100 == 0:
                elapsed = time.time() - scoring_start
                rate = processed_count / elapsed if elapsed > 0 else 0
                remaining = len(pinecone_matches) - processed_count
                eta = remaining / rate if rate > 0 else 0
                
                logger.info(f"   ⚡ Scored {processed_count}/{len(pinecone_matches)} ({rate:.1f}/sec, ETA: {eta:.0f}s)")
                sys.stdout.flush()
        
        scoring_duration = time.time() - scoring_start
        logger.info(f"✅ Scoring complete: {len(scored_matches)} matches (≥50% score) in {scoring_duration:.1f}s ({len(pinecone_matches)/scoring_duration:.1f} contracts/sec)")
        sys.stdout.flush()
        
        # Sort by match_score (already includes diversity boost from Pinecone scoring)
        scored_matches.sort(key=lambda x: x["scores"]["match_score"], reverse=True)
        
        # Keep top 500 for LLM re-ranking
        top_matches = scored_matches[:500]
        
        logger.info(f"🎯 Selected top {len(top_matches)} matches for LLM re-ranking")
        sys.stdout.flush()
        
        # ✅ PHASE 1.5 - LLM RE-RANKING
        llm_results = {}
        try:
            from app.services.llm_rerank_service import LLMReranker
            
            reranker = LLMReranker()
            llm_results = reranker.rerank_contracts_for_firm(firm, top_matches)
            
        except Exception as e:
            logger.error(f"⚠️ LLM re-ranking failed, using semantic scores only: {e}")
            # Continue with empty llm_results - will use fallback scores
        
        # Update matches with LLM data and calculate final scores
        for match in top_matches:
            # ✅ USE QDRANT_ID (which is Pinecone vector ID), NOT NOTICE_ID
            contract_id = match['contract'].qdrant_id
            
            if contract_id in llm_results:
                match['llm_data'] = llm_results[contract_id]
            else:
                # Fallback if LLM failed for this contract
                match['llm_data'] = {
                    'llm_score': 50,
                    'llm_verdict': 'monitor',
                    'llm_reasons': ['Semantic match only'],
                    'llm_flags': []
                }
            
            # ✅ FIXED SCORE NORMALIZATION
            # Both scores now on 0-100 scale for fair blending
            semantic_100 = match['scores']['match_score'] * 100  # 0.50-0.92 → 50-92
            llm_100 = match['llm_data']['llm_score']  # Already 0-100
            
            # Equal weight blend (50/50)
            final_100 = 0.5 * semantic_100 + 0.5 * llm_100
            match['final_score'] = final_100 / 100  # Back to 0-1 for storage
        
        # Re-sort by blended score
        top_matches.sort(key=lambda x: x['final_score'], reverse=True)
        
        phase1_duration = time.time() - phase1_start
        
        logger.info(f"")
        logger.info(f"🎯 Phase 1 Complete:")
        logger.info(f"   ⏱️  Total time: {phase1_duration/60:.1f} minutes")
        logger.info(f"   📊 Top match score: {top_matches[0]['final_score']:.2f}")
        logger.info(f"   📊 Contracts to cache: {len(top_matches)}")
        sys.stdout.flush()
        
        # Delete old cache entries for this firm
        logger.info(f"🗑️  Clearing old cache entries...")
        sys.stdout.flush()
        
        self.db.execute(
            delete(CachedContractMatch).where(
                CachedContractMatch.firm_id == firm.firm_id
            )
        )
        
        # Insert new cache entries with enrichment_status='pending'
        logger.info(f"💾 Saving {len(top_matches)} matches to cache...")
        sys.stdout.flush()
        
        for rank, match in enumerate(top_matches, start=1):
            contract = match["contract"]
            scores = match["scores"]
            metadata = match["metadata"]
            llm_data = match["llm_data"]
            
            # Prepare metadata dict
            cache_metadata = {
                "firm_id": firm.firm_id,
                "notice_id": contract.notice_id,
                "pinecone_id": contract.qdrant_id,  # ← Pinecone vector ID
                "title": contract.title,
                "buyer_name": contract.buyer_name,
                "description": contract.description,
                
                # Pre-computed scores
                "total_score": match['final_score'],  # ✅ Blended score (50/50)
                "final_score": match['final_score'],  # ✅ Required by database
                "capability_score": scores["capability_score"],
                "past_win_score": scores["past_win_score"],
                "preference_score": scores["preference_score"],
                
                # ✅ LLM Re-Rank Results (Phase 1.5)
                "llm_score": llm_data['llm_score'],
                "llm_verdict": llm_data['llm_verdict'],
                "llm_reasons": json.dumps(llm_data['llm_reasons']),
                "llm_flags": json.dumps(llm_data['llm_flags']),

                # Match context
                "matched_capabilities": scores.get("matched_capabilities", []),
                "why_this_matches": scores.get("why_this_matches", []),
                "match_reasons": scores.get("match_reasons", []),

                # ✅ Strategic intelligence = NULL (will be enriched in Phase 2)
                "incumbent_data": None,
                "pricing_benchmarks": None,
                "competition_stats": None,
                
                # ✅ Enrichment tracking
                "enrichment_status": "pending",
                "enriched_at": None,
                
                # Core Metadata
                "contract_value": metadata.get("contract_value"),
                "region": metadata.get("state"),
                "city": metadata.get("city"),
                "closing_date": metadata.get("response_deadline"),
                "posted_date": metadata.get("posted_date"),
                
                # Classification
                "naics_code": metadata.get("naics_code"),
                "psc_code": metadata.get("psc_code"),
                "set_aside": metadata.get("set_aside"),
                
                # Agency Info
                "office": metadata.get("office"),
                
                # Contact Information
                "contact_name": metadata.get("contact_name"),
                "contact_email": metadata.get("contact_email"),
                "contact_phone": metadata.get("contact_phone"),
                
                # Links
                "source_url": metadata.get("url"),
                
                # Ranking
                "rank": rank,
                "cached_at": datetime.now(timezone.utc)
            }
            
            # Truncate fields to prevent database errors
            cache_metadata = self._truncate_metadata(cache_metadata)
            
            # Create cached match record
            try:
                cached_match = CachedContractMatch(**cache_metadata)
                self.db.add(cached_match)
            except Exception as e:
                logger.error(f"Error creating cached match for {contract.notice_id}: {e}")
                continue
        
        # Commit all cached matches for this firm
        try:
            self.db.commit()
            logger.info(f"✅ PHASE 1 & 1.5 COMPLETE: Cached {len(top_matches)} matches for {firm.company_name}")
            logger.info(f"⏳ Strategic intelligence will be enriched in Phase 2...")
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"Error committing cached matches for firm {firm.firm_id}: {e}")
            self.db.rollback()
    
    def enrich_cached_matches_batched(self, firm_id: str):
        """
        PHASE 2: Add strategic intelligence using PSC-aware batched queries (15-20 min).
        
        ✨ NEW GROUPING STRATEGY: (PSC, NAICS, Agency) for contract-specific data
        
        Improvement Over Old Approach:
        OLD: Group by (NAICS, Agency) → 194 groups → agency-wide averages
             Example: All Air Force 541715 contracts → $5.8M avg (9,472 samples)
        
        NEW: Group by (PSC, NAICS, Agency) → 300-350 groups → contract-specific data
             Example: Air Force 541715 + PSC R425 → $2.3M avg (47 cloud migration contracts)
        
        Performance:
        - PSC-specific groups: ~60-70% of contracts (most have PSC codes)
        - NAICS-only fallback: ~30-40% of contracts (missing PSC codes)
        - Total queries: 300-400 (vs 194 before)
        - Estimated time: 15-20 minutes (vs 5-10 before)
        
        Data Quality:
        - PSC groups return "psc_specific" granularity (contract-level)
        - Fallback groups return "naics_agency" granularity (agency-level)
        - Frontend can show confidence indicators based on granularity
        """
        logger.info(f"")
        logger.info(f"{'='*80}")
        logger.info(f"🎯 PHASE 2: Enriching strategic intelligence for {firm_id}")
        logger.info(f"{'='*80}")
        sys.stdout.flush()
        
        # Get all pending matches
        matches = self.db.query(CachedContractMatch).filter(
            CachedContractMatch.firm_id == firm_id,
            CachedContractMatch.enrichment_status == 'pending'
        ).all()
        
        if not matches:
            logger.info(f"No pending matches to enrich for {firm_id}")
            return
        
        logger.info(f"📊 Enriching {len(matches)} contracts...")
        sys.stdout.flush()
        
        # ✅ BATCHING: Separate contracts by PSC availability
        psc_groups = {}      # Contracts WITH PSC codes → contract-specific data
        fallback_groups = {}  # Contracts WITHOUT PSC codes → agency-wide data
        
        for match in matches:
            naics = match.naics_code
            agency = match.buyer_name
            psc = match.psc_code
            
            # Skip contracts without basic classification
            if not naics or not agency:
                match.enrichment_status = 'complete'
                match.enriched_at = datetime.now(timezone.utc)
                continue
            
            # Group by PSC if available (CONTRACT-SPECIFIC)
            if psc and psc.strip():
                key = (psc.strip(), naics, agency)
                if key not in psc_groups:
                    psc_groups[key] = []
                psc_groups[key].append(match)
            else:
                # Fall back to NAICS + Agency (BROAD)
                key = (naics, agency)
                if key not in fallback_groups:
                    fallback_groups[key] = []
                fallback_groups[key].append(match)
        
        total_groups = len(psc_groups) + len(fallback_groups)
        logger.info(
            f"📊 Grouped into {len(psc_groups)} PSC-specific + "
            f"{len(fallback_groups)} NAICS-only groups "
            f"(total: {total_groups} queries)"
        )
        sys.stdout.flush()
        
        enriched_count = 0
        psc_specific_count = 0
        broad_fallback_count = 0
        
        # ✅ ENRICH PSC-SPECIFIC GROUPS (CONTRACT-LEVEL DATA)
        logger.info(f"🔍 Processing {len(psc_groups)} PSC-specific groups...")
        sys.stdout.flush()
        
        for idx, ((psc, naics, agency), contract_list) in enumerate(psc_groups.items()):
            if (idx + 1) % 50 == 0:
                logger.info(f"   ⚡ Processed {idx + 1}/{len(psc_groups)} PSC groups...")
                sys.stdout.flush()
            
            try:
                # Query with PSC for contract-level specificity
                pricing = self.scorer.incumbent_matcher.get_pricing_benchmarks(
                    naics_code=naics,
                    agency_name=agency,
                    psc_code=psc,  # ← KEY: Include PSC for contract-specific data
                    min_samples=10  # Require 10+ samples for confidence
                )
                
                competition = self.scorer.incumbent_matcher.get_competition_stats(
                    naics_code=naics,
                    agency_name=agency,
                    psc_code=psc,  # ← KEY: Include PSC for contract-specific data
                    min_samples=10
                )
                
                # Apply to all contracts in this PSC group
                for match in contract_list:
                    match.pricing_benchmarks = self._serialize_strategic_intel(pricing)
                    match.competition_stats = self._serialize_strategic_intel(competition)
                    match.enrichment_status = 'complete'
                    match.enriched_at = datetime.now(timezone.utc)
                    enriched_count += 1
                
                # Track granularity for reporting
                if pricing and pricing.get('granularity') == 'psc_specific':
                    psc_specific_count += len(contract_list)
                else:
                    broad_fallback_count += len(contract_list)
                
            except Exception as e:
                logger.error(f"Failed to enrich PSC group (PSC={psc}, NAICS={naics}, Agency={agency[:30]}): {e}")
                # Mark as complete to avoid retry loop
                for match in contract_list:
                    match.enrichment_status = 'complete'
                    match.enriched_at = datetime.now(timezone.utc)
        
        # ✅ ENRICH FALLBACK GROUPS (AGENCY-LEVEL DATA)
        logger.info(f"📊 Processing {len(fallback_groups)} NAICS-only groups...")
        sys.stdout.flush()
        
        for idx, ((naics, agency), contract_list) in enumerate(fallback_groups.items()):
            if (idx + 1) % 50 == 0:
                logger.info(f"   ⚡ Processed {idx + 1}/{len(fallback_groups)} NAICS groups...")
                sys.stdout.flush()
            
            try:
                # Query without PSC (agency-wide aggregation)
                pricing = self.scorer.incumbent_matcher.get_pricing_benchmarks(
                    naics_code=naics,
                    agency_name=agency,
                    psc_code=None,  # ← No PSC available
                    min_samples=3   # ← Lower threshold for fallback
                )
                
                competition = self.scorer.incumbent_matcher.get_competition_stats(
                    naics_code=naics,
                    agency_name=agency,
                    psc_code=None,
                    min_samples=3
                )
                
                # Apply to all contracts without PSC
                for match in contract_list:
                    match.pricing_benchmarks = self._serialize_strategic_intel(pricing)
                    match.competition_stats = self._serialize_strategic_intel(competition)
                    match.enrichment_status = 'complete'
                    match.enriched_at = datetime.now(timezone.utc)
                    enriched_count += 1
                
                broad_fallback_count += len(contract_list)
                
            except Exception as e:
                logger.error(f"Failed to enrich NAICS group (NAICS={naics}, Agency={agency[:30]}): {e}")
                for match in contract_list:
                    match.enrichment_status = 'complete'
                    match.enriched_at = datetime.now(timezone.utc)
        
        # Commit all enrichments
        try:
            self.db.commit()
            
            # Calculate percentages
            psc_pct = (psc_specific_count / enriched_count * 100) if enriched_count > 0 else 0
            broad_pct = (broad_fallback_count / enriched_count * 100) if enriched_count > 0 else 0
            
            logger.info(f"")
            logger.info(
                f"✅ PHASE 2 COMPLETE: Enriched {enriched_count}/{len(matches)} contracts for {firm_id}\n"
                f"   📊 Data Quality Breakdown:\n"
                f"      - {psc_specific_count} contracts ({psc_pct:.1f}%) got PSC-specific data (contract-level)\n"
                f"      - {broad_fallback_count} contracts ({broad_pct:.1f}%) got NAICS-only data (agency-level)\n"
                f"   🔍 Query Efficiency:\n"
                f"      - {len(psc_groups)} PSC-specific queries\n"
                f"      - {len(fallback_groups)} NAICS-only queries\n"
                f"      - Total: {total_groups} queries"
            )
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"Failed to commit enrichments: {e}")
            self.db.rollback()


# Standalone function for manual invocation
def refresh_cache_for_firm(firm_id: str):
    """
    Manually refresh cache for a single firm.
    Called after capability/past win changes.
    
    Runs all three phases:
    - Phase 1: Multi-query semantic matching with diversity boost
    - Phase 1.5: LLM re-ranking
    - Phase 2: PSC-aware strategic intelligence enrichment
    """
    service = MatchCacheService()
    service.run_cache_update(firm_ids=[firm_id])


if __name__ == "__main__":
    """
    Entry point for Railway cron job.
    
    Usage:
    1. Manual run: python app/services/match_cache_service.py
    2. Single firm: python -c "from app.services.match_cache_service import refresh_cache_for_firm; refresh_cache_for_firm('firm-abc123')"
    3. Railway cron: Runs automatically via Railway scheduler
    """
    import sys
    
    if len(sys.argv) > 1:
        # Run for specific firm
        firm_id = sys.argv[1]
        logger.info(f"Running cache update for single firm: {firm_id}")
        refresh_cache_for_firm(firm_id)
    else:
        # Run for all firms
        logger.info("Running cache update for all firms...")
        service = MatchCacheService()
        service.run_cache_update()