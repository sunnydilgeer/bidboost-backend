"""
Match Cache Service - Pre-computes contract matches for fast recommendations

This service:
1. Queries all companies with capabilities
2. Calculates match scores using capability vectors, past wins, and preferences
3. Stores top 100 matches per company in cached_contract_matches table
4. Runs nightly via cron to keep cache fresh

PERFORMANCE:
- Cache hit: ~50ms (database lookup)
- Cache miss: ~2-5s (Pinecone queries + scoring)
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import CompanyProfile, CachedContractMatch
from app.services.pinecone_store import PineconeStoreService
from app.services.capability_store_pinecone import get_capability_store
from app.services.past_win_store_pinecone import get_past_win_store
from app.services.matching_engine import MatchingEngine
from app.core.config import settings

logger = logging.getLogger(__name__)


class MatchCacheService:
    """Service for maintaining pre-computed contract match cache"""
    
    def __init__(self, db: Session = None):
        """Initialize cache service with database session"""
        self.db = db or SessionLocal()
        self.pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        self.capability_store = get_capability_store()
        self.past_win_store = get_past_win_store()
        self.matching_engine = MatchingEngine()
    
    def run_cache_update(self) -> Dict:
        """
        Main entry point: Update cache for all firms
        
        Returns summary of cache update operation
        """
        try:
            logger.info("🔄 Starting cache update...")
            
            # Get all companies
            firms = self.db.query(CompanyProfile).all()
            logger.info(f"🔄 Starting cache update for {len(firms)} firms...")
            
            summary = {
                "total_firms": len(firms),
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "errors": []
            }
            
            # Update cache for each firm
            for firm in firms:
                try:
                    if not firm.capabilities:
                        logger.warning(f"Firm {firm.firm_id} has no capabilities - skipping")
                        summary["skipped"] += 1
                        continue
                    
                    logger.info(f"Updating cache for {firm.company_name} (firm_id: {firm.firm_id})")
                    self._update_firm_cache(firm)
                    summary["updated"] += 1
                    
                except Exception as e:
                    logger.error(f"Failed to update cache for firm {firm.firm_id}: {e}")
                    summary["failed"] += 1
                    summary["errors"].append(f"{firm.firm_id}: {str(e)}")
                    # Continue with next firm instead of crashing
                    continue
            
            logger.info(f"✅ Cache update complete: {summary['updated']} updated, {summary['skipped']} skipped, {summary['failed']} failed")
            return summary
            
        except Exception as e:
            logger.error(f"Cache update failed: {e}")
            raise
    
    def _update_firm_cache(self, firm: CompanyProfile):
        """
        Update cached matches for a single firm
        
        Steps:
        1. Get firm's capability vectors from Pinecone
        2. Get firm's past win vectors from Pinecone
        3. Query top contracts using matching engine
        4. Delete old cache entries for this firm
        5. Insert new cache entries
        """
        # Step 1: Get capability vectors
        capability_ids = [cap.qdrant_id for cap in firm.capabilities if cap.qdrant_id]
        
        if not capability_ids:
            logger.warning(f"Firm {firm.firm_id} has no capability vectors - skipping")
            return
        
        capability_vectors = self.capability_store.get_capabilities_batch(capability_ids)
        
        if not capability_vectors:
            logger.error(f"No capability vectors found for firm {firm.firm_id}")
            return
        
        # Step 2: Get past win vectors (if any)
        past_win_ids = [win.pinecone_id for win in firm.past_wins if win.pinecone_id]
        past_win_vectors = {}
        
        if past_win_ids:
            past_win_vectors = self.past_win_store.get_past_wins_batch(past_win_ids)
        
        # Step 3: Get search preferences
        preferences = firm.search_preference
        
        # Step 4: Query contracts and calculate match scores
        matches = self.matching_engine.find_matching_contracts(
            capability_vectors=capability_vectors,
            past_win_vectors=past_win_vectors,
            preferences=preferences,
            firm_id=firm.firm_id,
            limit=100  # Cache top 100 matches
        )
        
        if not matches:
            logger.warning(f"No matches found for firm {firm.firm_id}")
            return
        
        # Step 5: Delete old cache entries for this firm
        self.db.query(CachedContractMatch).filter(
            CachedContractMatch.firm_id == firm.firm_id
        ).delete()
        
        # Step 6: Insert new cache entries
        cached_matches = []
        
        for idx, match_result in enumerate(matches):
            contract = match_result["contract"]
            
            # Prepare metadata dict
            match_metadata = {
                "firm_id": firm.firm_id,
                "notice_id": contract["notice_id"],
                "pinecone_id": contract.get("pinecone_id", ""),
                "title": contract.get("title", ""),
                "buyer_name": contract.get("buyer_name", ""),
                "description": contract.get("description", ""),
                "contract_value": contract.get("value", 0),
                "region": contract.get("region", ""),
                "closing_date": contract.get("response_deadline"),
                "posted_date": contract.get("posted_date"),
                "office": contract.get("office"),
                "naics_code": contract.get("naics_code"),
                "naics_name": contract.get("naics_name"),
                "psc_code": contract.get("psc_code"),
                "psc_name": contract.get("psc_name"),
                "set_aside": contract.get("set_aside"),
                "city": contract.get("city"),
                "source_url": contract.get("url"),
                "contact_name": contract.get("contact_name"),
                "contact_email": contract.get("contact_email"),
                "contact_phone": contract.get("contact_phone"),
                "total_score": match_result["match_scores"]["total_score"],
                "capability_score": match_result["match_scores"]["capability_score"],
                "past_win_score": match_result["match_scores"]["past_win_score"],
                "preference_score": match_result["match_scores"]["preference_score"],
                "match_reasons": match_result.get("match_reasons", []),
                "rank": idx + 1,
            }
            
            # 🔥 TRUNCATE FIELDS TO PREVENT DATABASE ERRORS
            match_metadata = self._truncate_metadata(match_metadata)
            
            # Create cached match record
            cached_match = CachedContractMatch(**match_metadata)
            cached_matches.append(cached_match)
        
        # Bulk insert all cached matches
        self.db.bulk_save_objects(cached_matches)
        self.db.commit()
        
        logger.info(f"✅ Cached {len(cached_matches)} matches for {firm.company_name}")
    
    def _truncate_metadata(self, metadata: dict) -> dict:
        """
        Truncate fields that exceed database VARCHAR limits.
        Prevents StringDataRightTruncation errors during cache update.
        
        🚨 CRITICAL FIX: Without this, cache cron crashes on firm-ibmer
        and blocks all firms alphabetically after it from getting fresh matches.
        
        This is a temporary fix - proper solution is to increase column sizes in DB.
        See: alembic migration increase_cache_varchar_limits
        
        Args:
            metadata: Contract metadata dict
            
        Returns:
            Same dict with truncated fields
        """
        # Define max lengths based on current schema
        max_lengths = {
            'office': 255,
            'naics_code': 255,
            'naics_name': 255,
            'psc_code': 255,
            'psc_name': 255,
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
    
    def get_cached_matches(
        self,
        firm_id: str,
        limit: int = 100,
        min_score: float = 0.0
    ) -> List[Dict]:
        """
        Retrieve cached matches for a firm
        
        Args:
            firm_id: Company firm_id
            limit: Maximum number of matches to return
            min_score: Minimum match score threshold
            
        Returns:
            List of cached match dicts
        """
        cached_matches = (
            self.db.query(CachedContractMatch)
            .filter(
                CachedContractMatch.firm_id == firm_id,
                CachedContractMatch.total_score >= min_score
            )
            .order_by(CachedContractMatch.rank)
            .limit(limit)
            .all()
        )
        
        # Convert to dict format expected by API
        return [match.to_dict() for match in cached_matches]
    
    def is_cache_stale(self, firm_id: str, max_age_hours: int = 24) -> bool:
        """
        Check if cache for a firm is stale
        
        Args:
            firm_id: Company firm_id
            max_age_hours: Maximum cache age in hours
            
        Returns:
            True if cache is stale or doesn't exist
        """
        latest_match = (
            self.db.query(CachedContractMatch)
            .filter(CachedContractMatch.firm_id == firm_id)
            .order_by(CachedContractMatch.cached_at.desc())
            .first()
        )
        
        if not latest_match:
            return True
        
        age = datetime.now(timezone.utc) - latest_match.cached_at
        return age.total_seconds() > (max_age_hours * 3600)
    
    def clear_cache_for_firm(self, firm_id: str):
        """Delete all cached matches for a firm"""
        deleted = (
            self.db.query(CachedContractMatch)
            .filter(CachedContractMatch.firm_id == firm_id)
            .delete()
        )
        self.db.commit()
        logger.info(f"Cleared {deleted} cached matches for firm {firm_id}")
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        total_firms = self.db.query(CompanyProfile).count()
        
        cached_firms = (
            self.db.query(CachedContractMatch.firm_id)
            .distinct()
            .count()
        )
        
        total_cached_matches = self.db.query(CachedContractMatch).count()
        
        return {
            "total_firms": total_firms,
            "cached_firms": cached_firms,
            "uncached_firms": total_firms - cached_firms,
            "total_cached_matches": total_cached_matches,
            "avg_matches_per_firm": total_cached_matches / cached_firms if cached_firms > 0 else 0
        }