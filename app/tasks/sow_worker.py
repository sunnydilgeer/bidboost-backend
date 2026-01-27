"""
Background worker for processing SOW extraction queue.

Run this separately from your main API:
    python -m app.tasks.sow_worker

Or schedule with cron/systemd to run every hour.
"""
import asyncio
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.sow_service import SOWService
from app.models.contract_sow import SOWExtractionQueue
from sqlalchemy import func

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def process_queue_worker(batch_size: int = 100):
    """
    Process pending SOW extraction queue items.
    
    Args:
        batch_size: Max number of items to process in one run
    """
    db = SessionLocal()
    sow_service = SOWService(db)
    
    try:
        logger.info(f"🚀 Starting SOW extraction worker (batch_size={batch_size})")
        
        # Get pending items (prioritize HIGH, then MEDIUM, then LOW)
        pending_items = db.query(SOWExtractionQueue).filter(
            SOWExtractionQueue.status == "PENDING"
        ).order_by(
            SOWExtractionQueue.priority.desc(),
            SOWExtractionQueue.created_at.asc()
        ).limit(batch_size).all()
        
        if not pending_items:
            logger.info("✅ No pending items in queue")
            return
        
        logger.info(f"📝 Found {len(pending_items)} pending items to process")
        
        processed = 0
        failed = 0
        
        for item in pending_items:
            try:
                logger.info(f"Processing {item.notice_id} (priority: {item.priority})")
                
                # Mark as processing
                item.status = "PROCESSING"
                db.commit()
                
                # TODO: Fetch contract and attachments
                # You'll need to integrate this with your contract fetcher/storage
                # For now, this is a placeholder
                
                # Example:
                # contract = fetch_contract_by_notice_id(item.notice_id)
                # attachments = parse_attachments(contract)
                # sow = await sow_service.extract_and_save_sow(
                #     notice_id=item.notice_id,
                #     attachments=attachments,
                #     description=contract.description
                # )
                
                # Mark as completed/failed
                # if sow:
                #     item.status = "COMPLETED"
                #     processed += 1
                # else:
                #     item.status = "FAILED"
                #     item.error_message = "SOW extraction returned None"
                #     failed += 1
                
                # For now, mark as failed with helpful message
                item.status = "FAILED"
                item.error_message = "Integration with contract fetcher needed"
                item.processed_at = func.now()
                failed += 1
                
                db.commit()
                
            except Exception as e:
                logger.error(f"Failed to process {item.notice_id}: {str(e)}")
                item.status = "FAILED"
                item.error_message = str(e)
                item.processed_at = func.now()
                failed += 1
                db.commit()
        
        logger.info(f"✅ Worker complete: {processed} processed, {failed} failed")
        
    except Exception as e:
        logger.error(f"Worker error: {str(e)}")
    finally:
        await sow_service.close()
        db.close()


if __name__ == "__main__":
    """Run the worker"""
    asyncio.run(process_queue_worker(batch_size=100))