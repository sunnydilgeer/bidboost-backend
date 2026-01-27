import logging
import json
from typing import List, Optional
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.services.contract_fetcher import ContractFetcherService
from app.services.vector_store import VectorStoreService
from app.services.sow_service import SOWService
from app.models.schemas import ContractOpportunity

logger = logging.getLogger(__name__)

class ContractSyncService:
    """
    Orchestrates contract fetching, SOW extraction, and vector storage.
    🆕 NOW DETECTS GARBAGE DESCRIPTIONS and queues SOW extraction
    """
    
    def __init__(self, db: Session, llm_service):
        self.db = db
        self.llm_service = llm_service
        self.contract_fetcher = ContractFetcherService()
        self.vector_store = VectorStoreService(db=db)
        self.sow_service = SOWService(db=db)
    
    async def close(self):
        """Close all services"""
        await self.contract_fetcher.close()
        await self.sow_service.close()
    
    async def sync_contracts(
        self,
        days_back: int = 7,
        extract_sows: bool = True,
        auto_queue: bool = True
    ) -> dict:
        """
        Main sync method: fetch contracts, extract SOWs, upsert to Pinecone.
        
        Args:
            days_back: How many days back to fetch
            extract_sows: Whether to extract SOWs immediately (or just queue)
            auto_queue: Auto-queue garbage descriptions for later extraction
            
        Returns:
            Sync statistics
        """
        try:
            logger.info(f"🚀 Starting contract sync (days_back={days_back})")
            
            # Step 1: Fetch contracts from SAM.gov
            published_from = datetime.utcnow() - timedelta(days=days_back)
            published_to = datetime.utcnow()
            
            all_contracts = []
            cursor = None
            
            while True:
                contracts, next_cursor = await self.contract_fetcher.fetch_contracts_with_cursor(
                    published_from=published_from,
                    published_to=published_to,
                    cursor=cursor
                )
                
                all_contracts.extend(contracts)
                
                if not next_cursor:
                    break
                cursor = next_cursor
            
            logger.info(f"📥 Fetched {len(all_contracts)} contracts from SAM.gov")
            
            # Step 2: Process each contract for SOW extraction
            sows_extracted = 0
            sows_queued = 0
            
            for contract in all_contracts:
                # Check if description is garbage
                needs_sow = self.sow_service.should_extract_sow(contract.description)
                
                if needs_sow:
                    # Parse attachments
                    attachments = []
                    if contract.attachments:
                        try:
                            attachments = json.loads(contract.attachments)
                        except:
                            logger.warning(f"Failed to parse attachments for {contract.notice_id}")
                    
                    if attachments:
                        if extract_sows:
                            # Extract SOW immediately
                            sow = await self.sow_service.extract_and_save_sow(
                                notice_id=contract.notice_id,
                                attachments=attachments,
                                description=contract.description
                            )
                            if sow:
                                sows_extracted += 1
                        elif auto_queue:
                            # Queue for later extraction
                            self.sow_service.add_to_queue(
                                notice_id=contract.notice_id,
                                priority="MEDIUM",
                                reason="Garbage description detected"
                            )
                            sows_queued += 1
            
            logger.info(f"🔍 SOWs extracted: {sows_extracted}, queued: {sows_queued}")
            
            # Step 3: Convert contracts to dicts for Pinecone
            contract_dicts = [
                {
                    "notice_id": c.notice_id,
                    "title": c.title,
                    "description": c.description,
                    "buyer_name": c.buyer_name,
                    "value": c.value,
                    "region": c.region,
                    "closing_date": c.closing_date.isoformat() if c.closing_date else None,
                    "cpv_codes": c.cpv_codes,
                    # Add any other fields you need
                }
                for c in all_contracts
            ]
            
            # Step 4: Upsert to Pinecone (will use SOW text automatically)
            await self.vector_store.upsert_contracts(contract_dicts, self.llm_service)
            
            logger.info(f"✅ Contract sync complete!")
            
            return {
                "success": True,
                "contracts_fetched": len(all_contracts),
                "sows_extracted": sows_extracted,
                "sows_queued": sows_queued,
                "contracts_upserted": len(contract_dicts),
                "message": f"Synced {len(all_contracts)} contracts, extracted {sows_extracted} SOWs"
            }
            
        except Exception as e:
            logger.error(f"Contract sync failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "Contract sync failed"
            }