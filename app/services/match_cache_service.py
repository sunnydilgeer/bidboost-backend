"""
Background Job: Pre-compute Contract Matches

Runs nightly to cache top 100 matches per company in PostgreSQL
"""

import logging
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import delete
from datetime import datetime, timezone

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
    
    OPUS PURE CAPABILITY APPROACH:
    - Uses match_score (capability similarity only)
    - No weighted average, no penalties
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
                    self._update_firm_cache(firm)
                except Exception as e:
                    logger.error(f"Failed to update cache for firm {firm.firm_id}: {e}")
                    continue
            
            logger.info(f"✅ Cache update complete for {len(firms)} firms")
            
        except Exception as e:
            logger.error(f"Cache update failed: {e}", exc_info=True)
        finally:
            if self.db:
                self.db.close()
    
    def _update_firm_cache(self, firm: CompanyProfile):
        """
        Update cached matches for a single firm.
        """
        logger.info(f"Updating cache for {firm.company_name} (firm_id: {firm.firm_id})")
        
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
        
        # Get contracts from Pinecone (top 500 by semantic similarity)
        first_cap_vector = capability_vectors.get(capability_ids[0])
        if not first_cap_vector:
            logger.warning(f"No vector for first capability - skipping firm {firm.firm_id}")
            return
        
        search_results = self.pinecone.index.query(
            vector=first_cap_vector,
            namespace="contracts",
            top_k=500,
            include_metadata=True,
            include_values=True
        )
        
        # Score each contract
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
                qdrant_id=result.id
            )
            
            # Score the contract
            scores = self.scorer.score_contract(
                contract=contract,
                firm_id=firm.firm_id,
                capability_vectors=capability_vectors,
                contract_vectors={result.id: result.values},
                past_win_vectors=past_win_vectors
            )
            
            if scores and scores["match_score"] >= 0.5:  # Only cache 50%+ matches
                scored_matches.append({
                    "contract": contract,
                    "scores": scores,
                    "metadata": metadata
                })
        
        # Sort by match_score (PURE CAPABILITY)
        scored_matches.sort(key=lambda x: x["scores"]["match_score"], reverse=True)
        
        # Keep top 100
        top_matches = scored_matches[:100]
        
        # Delete old cache entries for this firm
        self.db.execute(
            delete(CachedContractMatch).where(
                CachedContractMatch.firm_id == firm.firm_id
            )
        )
        
        # Insert new cache entries with ALL fields
        for rank, match in enumerate(top_matches, start=1):
            contract = match["contract"]
            scores = match["scores"]
            metadata = match["metadata"]
            
            cached_match = CachedContractMatch(
                firm_id=firm.firm_id,
                notice_id=contract.notice_id,
                pinecone_id=contract.qdrant_id,
                title=contract.title,
                buyer_name=contract.buyer_name,
                description=contract.description,
                
                # Pre-computed scores (PURE CAPABILITY)
                total_score=scores["match_score"],
                capability_score=scores["capability_score"],
                past_win_score=scores["past_win_score"],
                preference_score=scores["preference_score"],
                
                # Core Metadata
                contract_value=metadata.get("contract_value"),
                region=metadata.get("state"),
                city=metadata.get("city"),
                closing_date=metadata.get("response_deadline"),
                posted_date=metadata.get("posted_date"),
                
                # Classification
                naics_code=metadata.get("naics_code"),
                psc_code=metadata.get("psc_code"),
                set_aside=metadata.get("set_aside"),
                
                # Agency Info
                office=metadata.get("office"),
                
                # Contact Information
                contact_name=metadata.get("contact_name"),
                contact_email=metadata.get("contact_email"),
                contact_phone=metadata.get("contact_phone"),
                
                # Links
                source_url=metadata.get("url"),
                
                # Ranking
                rank=rank,
                cached_at=datetime.now(timezone.utc)
            )
            
            self.db.add(cached_match)
        
        self.db.commit()
        
        logger.info(f"✅ Cached {len(top_matches)} matches for {firm.company_name}")


# Standalone function for manual invocation
def refresh_cache_for_firm(firm_id: str):
    """
    Manually refresh cache for a single firm.
    Called after capability/past win changes.
    """
    service = MatchCacheService()
    service.run_cache_update(firm_ids=[firm_id])