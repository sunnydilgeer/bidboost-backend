"""
Background worker for processing SOW extraction queue.

This worker:
1. Fetches contracts from sow_extraction_queue
2. Scrapes SAM.gov for attachment URLs
3. Downloads PDFs
4. Extracts SOW text
5. Updates Pinecone with SOW-based embeddings

Usage:
    python -m app.tasks.sow_extraction_worker
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import SessionLocal
from app.models.contract_sow import ContractSOW, SOWExtractionQueue
from app.services.sam_attachment_scraper import SAMAttachmentScraper
from app.services.sow_extractor import SOWExtractor
from app.services.sow_service import SOWService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SOWExtractionWorker:
    """Background worker for processing SOW extraction queue."""
    
    def __init__(self, db: Session, batch_size: int = 50):
        """
        Initialize worker.
        
        Args:
            db: Database session
            batch_size: Number of items to process per batch
        """
        self.db = db
        self.batch_size = batch_size
        self.scraper = None
        self.sow_service = SOWService(db)
        
    async def initialize(self):
        """Initialize scraper."""
        self.scraper = SAMAttachmentScraper(headless=True)
        await self.scraper.initialize()
        logger.info("Worker initialized")
    
    async def close(self):
        """Cleanup resources."""
        if self.scraper:
            await self.scraper.close()
        logger.info("Worker closed")
    
    async def process_queue(self):
        """Process items in the extraction queue."""
        # Get pending items from queue (prioritize HIGH → MEDIUM → LOW)
        queue_items = (
            self.db.query(SOWExtractionQueue)
            .filter(SOWExtractionQueue.status == "PENDING")
            .order_by(
                SOWExtractionQueue.priority.desc(),
                SOWExtractionQueue.created_at.asc()
            )
            .limit(self.batch_size)
            .all()
        )
        
        if not queue_items:
            logger.info("Queue is empty")
            return 0
        
        logger.info(f"Processing {len(queue_items)} items from queue")
        
        processed = 0
        failed = 0
        
        for item in queue_items:
            try:
                # Mark as processing
                item.status = "PROCESSING"
                self.db.commit()
                
                logger.info(f"Processing notice_id: {item.notice_id}")
                
                # Step 1: Scrape attachments from SAM.gov
                result = await self.scraper.get_attachments(item.notice_id)
                
                if not result.get('success'):
                    raise Exception(result.get('error', 'Unknown scraping error'))
                
                attachments = result.get('attachments', [])
                
                if not attachments:
                    logger.warning(f"No attachments found for {item.notice_id}")
                    item.status = "COMPLETED"
                    item.error_message = "No attachments found"
                    item.processed_at = datetime.utcnow()
                    self.db.commit()
                    continue
                
                # Step 2: Extract SOW from best attachment
                # Select best attachment (prefer SOW/PWS files)
                best_attachment = self._select_best_attachment(attachments)
                
                if not best_attachment:
                    logger.warning(f"No suitable PDF attachment for {item.notice_id}")
                    item.status = "COMPLETED"
                    item.error_message = "No suitable PDF attachment"
                    item.processed_at = datetime.utcnow()
                    self.db.commit()
                    continue
                
                logger.info(f"Selected attachment: {best_attachment['filename']}")
                
                # Step 3: Extract SOW text from PDF
                sow_result = await self.sow_service.extract_and_save_sow(
                    notice_id=item.notice_id,
                    attachments=attachments,
                    description=result.get('description', '')
                )
                
                if sow_result:
                    logger.info(f"✅ SOW extracted for {item.notice_id} - {sow_result.word_count} words")
                    item.status = "COMPLETED"
                    processed += 1
                else:
                    logger.warning(f"SOW extraction returned None for {item.notice_id}")
                    item.status = "FAILED"
                    item.error_message = "SOW extraction returned None"
                    failed += 1
                
                item.processed_at = datetime.utcnow()
                self.db.commit()
                
            except Exception as e:
                logger.error(f"Failed to process {item.notice_id}: {str(e)}")
                item.status = "FAILED"
                item.error_message = str(e)[:500]
                item.processed_at = datetime.utcnow()
                self.db.commit()
                failed += 1
        
        logger.info(f"Batch complete: {processed} processed, {failed} failed")
        return processed
    
    def _select_best_attachment(self, attachments: List[dict]) -> dict:
        """
        Select the best attachment for SOW extraction.
        
        Priority:
        1. Files with "SOW" or "PWS" in name
        2. Files with "Solicitation" in name
        3. Any PDF file
        
        Args:
            attachments: List of attachment dicts
            
        Returns:
            Best attachment dict or None
        """
        if not attachments:
            return None
        
        # Priority 1: SOW/PWS files
        for att in attachments:
            filename = att.get('filename', '').lower()
            if any(keyword in filename for keyword in ['sow', 'pws', 'statement of work']):
                return att
        
        # Priority 2: Solicitation files
        for att in attachments:
            filename = att.get('filename', '').lower()
            if 'solicitation' in filename:
                return att
        
        # Priority 3: Any PDF
        for att in attachments:
            url = att.get('url', '').lower()
            if '.pdf' in url:
                return att
        
        # Fallback: first attachment
        return attachments[0]


async def main():
    """Main worker loop."""
    logger.info("=" * 70)
    logger.info("SOW EXTRACTION WORKER - STARTING")
    logger.info("=" * 70)
    
    db = SessionLocal()
    worker = SOWExtractionWorker(db, batch_size=50)
    
    try:
        await worker.initialize()
        
        # Process queue
        processed = await worker.process_queue()
        
        logger.info("=" * 70)
        logger.info(f"WORKER COMPLETE - Processed {processed} items")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"Worker error: {str(e)}")
        raise
    finally:
        await worker.close()
        db.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())