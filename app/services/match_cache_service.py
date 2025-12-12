"""
Background Job: Pre-compute Contract Matches
Runs nightly to cache top 100 matches per company in PostgreSQL
"""
import logging
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import delete
from datetime import datetime
from app.database import SessionLocal
from app.models.company import CompanyProfile, CachedContractMatch
from app.services.match_scoring import ContractMatchScorer
from app.services.pinecone_store import PineconeStoreService
from app.services.capability_store_pinecone import get_capability_store
from app.services.past_win_store_pinecone import get_past_win_store
from app.services.code_lookup import get_code_lookup_service
from app.core.config import settings

logger = logging.getLogger(__name__)

class MatchCacheService:
    """
    Service to pre-compute and cache contract matches.
    Run this nightly via cron job or scheduler.
    """
    
    def __init__(self):
        self.db = SessionLocal()
        self.pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        self.scorer = ContractMatchScorer(self.db, self.pinecone.index)
        self.code_service = get_code_lookup_service()
        self.cap_store = get_capability_store()
        self.win_store = get_past_win_store()
    
    def run_cache_update(self, max_companies: int = None) -> Dict[str, int]:
        """
        Main entry point: Update cache for all companies.
        
        Args:
            max_companies: Limit number of companies (for testing)
        
        Returns:
            Stats dict: {companies_processed, matches_cached, errors}
        """
        stats = {
            "companies_processed": 0,
            "matches_cached": 0,
            "errors": 0,
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": None
        }
        
        try:
            logger.info("🚀 Starting nightly match cache update...")
            
            # Get all companies with capabilities
            query = self.db.query(CompanyProfile).filter(
                CompanyProfile.capabilities.any()  # Only process companies with capabilities
            )
            
            if max_companies:
                query = query.limit(max_companies)
            
            companies = query.all()
            logger.info(f"📊 Found {len(companies)} companies to process")
            
            for company in companies:
                try:
                    matches_cached = self._cache_matches_for_company(company)
                    stats["companies_processed"] += 1
                    stats["matches_cached"] += matches_cached
                    
                    if stats["companies_processed"] % 10 == 0:
                        logger.info(f"✅ Processed {stats['companies_processed']}/{len(companies)} companies")
                
                except Exception as e:
                    logger.error(f"❌ Failed to cache matches for {company.firm_id}: {e}")
                    stats["errors"] += 1
            
            stats["completed_at"] = datetime.utcnow().isoformat()
            logger.info(f"🎉 Cache update complete! {stats}")
            
            return stats
        
        except Exception as e:
            logger.error(f"❌ Fatal error in cache update: {e}", exc_info=True)
            stats["errors"] += 1
            return stats
        
        finally:
            self.db.close()
    
    def _cache_matches_for_company(self, company: CompanyProfile) -> int:
        """
        Pre-compute and cache top 100 matches for a single company.
        
        Returns:
            Number of matches cached
        """
        try:
            firm_id = company.firm_id
            logger.info(f"🔍 Processing company: {company.company_name} ({firm_id})")
            
            # STEP 1: Get company capabilities and create query
            capabilities = company.capabilities
            if not capabilities:
                logger.warning(f"No capabilities for {firm_id}, skipping")
                return 0
            
            # Create combined query from capabilities
            capability_texts = [cap.capability_text for cap in capabilities[:3]]
            combined_query = " ".join(capability_texts)
            
            # Generate embedding (you'll need to import your LLM service)
            from app.services.llm import generate_embeddings_sync
            query_vector = generate_embeddings_sync(combined_query)
            
            # STEP 2: Search Pinecone for candidate contracts
            results = self.pinecone.search_contracts(
                query_vector=query_vector,
                limit=200,  # Get more candidates to score
                min_score=0.40,  # Lower threshold to ensure enough results
                namespace="contracts"
            )
            
            if not results:
                logger.warning(f"No contracts found for {firm_id}")
                return 0
            
            logger.info(f"📋 Found {len(results)} candidate contracts for {firm_id}")
            
            # STEP 3: Pre-fetch all vectors for batch scoring
            capability_vectors = self._prefetch_capability_vectors(capabilities)
            past_win_vectors = self._prefetch_past_win_vectors(company.past_wins)
            contract_vectors = self._prefetch_contract_vectors(results)
            
            # STEP 4: Score all contracts
            scored_matches = []
            
            for result in results:
                enriched = self.code_service.enrich_contract(result)
                
                # Create temp Contract for scoring
                from app.models.contract import Contract
                temp_contract = Contract(
                    notice_id=enriched.get("notice_id", ""),
                    title=enriched.get("title", ""),
                    buyer_name=enriched.get("agency", ""),
                    description=enriched.get("description", ""),
                    contract_value=enriched.get("contract_value"),
                    region=enriched.get("state"),
                    qdrant_id=enriched.get("id")
                )
                
                # Score it
                match_scores = self.scorer.score_contract(
                    temp_contract,
                    firm_id,
                    capability_vectors=capability_vectors,
                    contract_vectors=contract_vectors,
                    past_win_vectors=past_win_vectors
                )
                
                if match_scores:
                    scored_matches.append({
                        "enriched": enriched,
                        "scores": match_scores
                    })
            
            # STEP 5: Sort by total_score and take top 100
            scored_matches.sort(key=lambda x: x["scores"]["total_score"], reverse=True)
            top_matches = scored_matches[:100]
            
            logger.info(f"💯 Top match score for {firm_id}: {top_matches[0]['scores']['total_score']}")
            
            # STEP 6: Delete old cache for this company
            self.db.execute(
                delete(CachedContractMatch).where(
                    CachedContractMatch.firm_id == firm_id
                )
            )
            
            # STEP 7: Insert new cached matches
            cached_records = []
            for rank, match_data in enumerate(top_matches, start=1):
                enriched = match_data["enriched"]
                scores = match_data["scores"]
                
                cached_records.append(CachedContractMatch(
                    firm_id=firm_id,
                    notice_id=enriched.get("notice_id", ""),
                    pinecone_id=enriched.get("id", ""),
                    
                    # Contract data
                    title=enriched.get("title", ""),
                    buyer_name=enriched.get("agency", ""),
                    description=enriched.get("description", ""),
                    contract_value=enriched.get("contract_value"),
                    region=enriched.get("state"),
                    closing_date=enriched.get("response_deadline"),
                    posted_date=enriched.get("posted_date"),
                    
                    # Enriched data
                    office=enriched.get("office"),
                    naics_code=enriched.get("naics_code"),
                    naics_name=enriched.get("naics_name"),
                    psc_code=enriched.get("psc_code"),
                    psc_name=enriched.get("psc_name"),
                    set_aside=enriched.get("set_aside"),
                    city=enriched.get("city"),
                    source_url=enriched.get("url"),
                    contact_name=enriched.get("contact_name"),
                    contact_email=enriched.get("contact_email"),
                    contact_phone=enriched.get("contact_phone"),
                    
                    # Pre-computed scores
                    total_score=scores["total_score"],
                    capability_score=scores["capability_score"],
                    past_win_score=scores["past_win_score"],
                    preference_score=scores["preference_score"],
                    match_reasons=scores.get("match_reasons", []),
                    
                    # Rank
                    rank=rank
                ))
            
            self.db.bulk_save_objects(cached_records)
            self.db.commit()
            
            logger.info(f"✅ Cached {len(cached_records)} matches for {firm_id}")
            return len(cached_records)
        
        except Exception as e:
            logger.error(f"❌ Error caching matches for {company.firm_id}: {e}", exc_info=True)
            self.db.rollback()
            raise
    
    def _prefetch_capability_vectors(self, capabilities) -> Dict:
        """Pre-fetch capability vectors in batch"""
        capability_ids = [cap.qdrant_id for cap in capabilities if cap.qdrant_id]
        if not capability_ids:
            return {}
        
        return self.cap_store.get_capabilities_batch(capability_ids)
    
    def _prefetch_past_win_vectors(self, past_wins) -> Dict:
        """Pre-fetch past win vectors in batch"""
        if not past_wins:
            return {}
        
        win_ids = [win.pinecone_id for win in past_wins if win.pinecone_id]
        if not win_ids:
            return {}
        
        return self.win_store.get_past_wins_batch(win_ids)
    
    def _prefetch_contract_vectors(self, results: List[Dict]) -> Dict:
        """Pre-fetch contract vectors in batch"""
        contract_ids = [r.get("id") for r in results if r.get("id")]
        if not contract_ids:
            return {}
        
        try:
            fetch_result = self.pinecone.index.fetch(ids=contract_ids, namespace="contracts")
            return {vec_id: list(vec_data.values) for vec_id, vec_data in fetch_result.vectors.items()}
        except Exception as e:
            logger.error(f"Failed to batch fetch contract vectors: {e}")
            return {}


# CLI entry point for running the job
if __name__ == "__main__":
    import sys
    
    # Usage: python -m app.services.match_cache_service [max_companies]
    max_companies = int(sys.argv[1]) if len(sys.argv) > 1 else None
    
    service = MatchCacheService()
    stats = service.run_cache_update(max_companies=max_companies)
    
    print(f"\n📊 Cache Update Complete:")
    print(f"   Companies: {stats['companies_processed']}")
    print(f"   Matches: {stats['matches_cached']}")
    print(f"   Errors: {stats['errors']}")
    print(f"   Duration: {stats['started_at']} → {stats['completed_at']}")