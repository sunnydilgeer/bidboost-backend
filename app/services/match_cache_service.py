"""
Background Job: Pre-compute Contract Matches - TWO-PHASE STRATEGY

Phase 1: Fast semantic matching (2-5 min)
Phase 2: Batched strategic intelligence enrichment (5-10 min, async)

Runs nightly to cache top 500 matches per company in PostgreSQL
"""

import logging
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import delete
from datetime import datetime, timezone
import json

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
    
    TWO-PHASE CACHING STRATEGY:
    Phase 1: Semantic matching only (fast, 2-5 min)
    Phase 2: Strategic intelligence via batched queries (5-10 min)
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
            
            for firm in firms:
                try:
                    # PHASE 1: Fast matching (2-5 min)
                    self._update_firm_cache(firm)
                    
                    # PHASE 2: Strategic intelligence enrichment (5-10 min)
                    self.enrich_cached_matches_batched(firm.firm_id)
                    
                except Exception as e:
                    logger.error(f"Failed to update cache for firm {firm.firm_id}: {e}")
                    continue
            
            logger.info(f"✅ Cache update complete for {len(firms)} firms")
            
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
        - pricing_benchmarks: Dict with avg/min/max awards
        - competition_stats: Dict with avg offers and set-aside distribution
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
        PHASE 1: Fast semantic matching only (2-5 min).
        
        Skips strategic intelligence queries to maximize speed.
        Matches are saved with enrichment_status='pending' for Phase 2.
        """
        logger.info(f"⚡ PHASE 1: Fast matching for {firm.company_name} (firm_id: {firm.firm_id})")
        
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
        
        capability_vectors = cap_store.get_capabilities_batch(capability_ids)
        
        # Pre-fetch past win vectors (if any)
        past_win_vectors = {}
        if firm.past_wins:
            from app.services.past_win_store_pinecone import get_past_win_store
            win_store = get_past_win_store()
            past_win_ids = [win.pinecone_id for win in firm.past_wins if win.pinecone_id]
            if past_win_ids:
                past_win_vectors = win_store.get_past_wins_batch(past_win_ids)
        
        # Get contracts from Pinecone (top 1000 by semantic similarity)
        first_cap_vector = capability_vectors.get(capability_ids[0])
        if not first_cap_vector:
            logger.warning(f"No vector for first capability - skipping firm {firm.firm_id}")
            return
        
        search_results = self.pinecone.index.query(
            vector=first_cap_vector,
            namespace="contracts",
            top_k=1000,
            include_metadata=True,
            include_values=True
        )
        
        # Score each contract WITHOUT strategic intelligence
        scored_matches = []
        for result in search_results.matches:
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
                qdrant_id=result.id,
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
                    "metadata": metadata
                })
        
        # Sort by match_score (PURE CAPABILITY)
        scored_matches.sort(key=lambda x: x["scores"]["match_score"], reverse=True)
        
        # Keep top 500
        top_matches = scored_matches[:500]
        
        logger.info(f"Found {len(top_matches)} matches (50%+ score) for {firm.company_name}")
        
        # Delete old cache entries for this firm
        self.db.execute(
            delete(CachedContractMatch).where(
                CachedContractMatch.firm_id == firm.firm_id
            )
        )
        
        # Insert new cache entries with enrichment_status='pending'
        for rank, match in enumerate(top_matches, start=1):
            contract = match["contract"]
            scores = match["scores"]
            metadata = match["metadata"]
            
            # Prepare metadata dict
            cache_metadata = {
                "firm_id": firm.firm_id,
                "notice_id": contract.notice_id,
                "pinecone_id": contract.qdrant_id,
                "title": contract.title,
                "buyer_name": contract.buyer_name,
                "description": contract.description,
                
                # Pre-computed scores (PURE CAPABILITY - Phase 1)
                "total_score": scores["match_score"],
                "capability_score": scores["capability_score"],
                "past_win_score": scores["past_win_score"],
                "preference_score": scores["preference_score"],

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
            logger.info(f"✅ PHASE 1 COMPLETE: Cached {len(top_matches)} matches for {firm.company_name}")
            logger.info(f"⏳ Strategic intelligence will be enriched in Phase 2...")
        except Exception as e:
            logger.error(f"Error committing cached matches for firm {firm.firm_id}: {e}")
            self.db.rollback()
    
    def enrich_cached_matches_batched(self, firm_id: str):
        """
        PHASE 2: Add strategic intelligence using batched queries (5-10 min).
        
        Deduplicates by (NAICS, Agency) to reduce 500 queries → 50-100 queries.
        Example: 50 contracts with same NAICS+Agency = 1 query instead of 50.
        """
        logger.info(f"🎯 PHASE 2: Enriching strategic intelligence for {firm_id}")
        
        # Get all pending matches
        matches = self.db.query(CachedContractMatch).filter(
            CachedContractMatch.firm_id == firm_id,
            CachedContractMatch.enrichment_status == 'pending'
        ).all()
        
        if not matches:
            logger.info(f"No pending matches to enrich for {firm_id}")
            return
        
        logger.info(f"Enriching {len(matches)} contracts...")
        
        # ✅ BATCH DEDUPLICATION: Group by unique (NAICS, Agency) pairs
        unique_pairs = {}
        for match in matches:
            key = (match.naics_code, match.buyer_name)
            if key not in unique_pairs:
                unique_pairs[key] = []
            unique_pairs[key].append(match)
        
        logger.info(f"Deduplicated to {len(unique_pairs)} unique (NAICS, Agency) pairs")
        
        # Query ONCE per unique pair
        enriched_count = 0
        for (naics, agency), contract_list in unique_pairs.items():
            if not naics or not agency:
                # Skip contracts without NAICS/Agency data
                for match in contract_list:
                    match.enrichment_status = 'complete'
                    match.enriched_at = datetime.now(timezone.utc)
                continue
            
            try:
                # Get pricing benchmarks (1 query for all contracts with same NAICS+Agency)
                pricing = self.scorer.incumbent_matcher.get_pricing_benchmarks(naics, agency)
                
                # Get competition stats (1 query for all contracts with same NAICS+Agency)
                competition = self.scorer.incumbent_matcher.get_competition_stats(naics, agency)
                
                # Apply to ALL contracts with same NAICS+Agency
                for match in contract_list:
                    match.pricing_benchmarks = self._serialize_strategic_intel(pricing)
                    match.competition_stats = self._serialize_strategic_intel(competition)
                    match.enrichment_status = 'complete'
                    match.enriched_at = datetime.now(timezone.utc)
                    enriched_count += 1
                
                logger.debug(f"Enriched {len(contract_list)} contracts for NAICS={naics}, Agency={agency[:30]}...")
                
            except Exception as e:
                logger.error(f"Failed to enrich (NAICS={naics}, Agency={agency}): {e}")
                # Mark as complete anyway to avoid retry loop
                for match in contract_list:
                    match.enrichment_status = 'complete'
                    match.enriched_at = datetime.now(timezone.utc)
        
        # Commit all enrichments
        try:
            self.db.commit()
            logger.info(f"✅ PHASE 2 COMPLETE: Enriched {enriched_count}/{len(matches)} contracts for {firm_id}")
        except Exception as e:
            logger.error(f"Failed to commit enrichments: {e}")
            self.db.rollback()


# Standalone function for manual invocation
def refresh_cache_for_firm(firm_id: str):
    """
    Manually refresh cache for a single firm.
    Called after capability/past win changes.
    
    Runs both Phase 1 (fast matching) and Phase 2 (enrichment).
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