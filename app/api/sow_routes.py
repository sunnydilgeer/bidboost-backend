from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
import logging

from app.database import get_db
from app.models.schemas import (
    SOWExtractionRequest,
    SOWResponse,
    SOWExtractionStats,
    SOWQueueStatus
)
from app.services.sow_service import SOWService
from app.models.contract_sow import ContractSOW, SOWExtractionQueue
from sqlalchemy import func

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/sow", tags=["SOW Extraction Admin"])


@router.get("/stats", response_model=SOWExtractionStats)
async def get_sow_stats(db: Session = Depends(get_db)):
    """
    Get statistics about SOW extraction system.
    
    Returns:
        - Total contracts with SOWs
        - Confidence breakdown
        - Queue status
        - Average word count
    """
    try:
        # Contract SOW stats
        total_sows = db.query(ContractSOW).count()
        high_confidence = db.query(ContractSOW).filter(
            ContractSOW.confidence == "HIGH"
        ).count()
        medium_confidence = db.query(ContractSOW).filter(
            ContractSOW.confidence == "MEDIUM"
        ).count()
        low_confidence = db.query(ContractSOW).filter(
            ContractSOW.confidence == "LOW"
        ).count()
        
        # Average word count
        avg_words = db.query(func.avg(ContractSOW.word_count)).scalar()
        
        # Queue stats
        sow_service = SOWService(db)
        queue_stats = sow_service.get_queue_stats()
        
        return SOWExtractionStats(
            total_contracts=0,  # You can add this from your contracts table
            contracts_with_sow=total_sows,
            high_confidence=high_confidence,
            medium_confidence=medium_confidence,
            low_confidence=low_confidence,
            queue_status=SOWQueueStatus(**queue_stats),
            avg_word_count=float(avg_words) if avg_words else None
        )
        
    except Exception as e:
        logger.error(f"Failed to get SOW stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notice_id}", response_model=SOWResponse)
async def get_sow_by_notice_id(
    notice_id: str,
    db: Session = Depends(get_db)
):
    """
    Get extracted SOW for a specific contract.
    
    Args:
        notice_id: Contract notice ID
        
    Returns:
        SOW data if exists, 404 if not found
    """
    sow_service = SOWService(db)
    sow = sow_service.get_sow(notice_id)
    
    if not sow:
        raise HTTPException(
            status_code=404,
            detail=f"No SOW found for contract {notice_id}"
        )
    
    return sow


@router.post("/extract/{notice_id}")
async def extract_sow_manual(
    notice_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Manually trigger SOW extraction for a specific contract.
    
    This is useful for:
    - Retrying failed extractions
    - Extracting SOW for specific high-value contracts
    - Testing the extraction pipeline
    
    Args:
        notice_id: Contract notice ID
        
    Returns:
        Status message
    """
    try:
        sow_service = SOWService(db)
        
        # Check if SOW already exists
        existing = sow_service.get_sow(notice_id)
        if existing:
            return {
                "success": True,
                "message": f"SOW already exists for {notice_id}",
                "confidence": existing.confidence,
                "word_count": existing.word_count
            }
        
        # Add to queue with HIGH priority
        queue_item = sow_service.add_to_queue(
            notice_id=notice_id,
            priority="HIGH",
            reason="Manual extraction requested"
        )
        
        return {
            "success": True,
            "message": f"Added {notice_id} to extraction queue",
            "queue_id": queue_item.id,
            "status": queue_item.status
        }
        
    except Exception as e:
        logger.error(f"Failed to queue SOW extraction for {notice_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue/status")
async def get_queue_status(db: Session = Depends(get_db)):
    """
    Get current status of SOW extraction queue.
    
    Returns:
        Queue statistics and recent items
    """
    try:
        sow_service = SOWService(db)
        stats = sow_service.get_queue_stats()
        
        # Get recent queue items
        recent_items = db.query(SOWExtractionQueue).order_by(
            SOWExtractionQueue.created_at.desc()
        ).limit(20).all()
        
        return {
            "stats": stats,
            "recent_items": [
                {
                    "id": item.id,
                    "notice_id": item.notice_id,
                    "priority": item.priority,
                    "status": item.status,
                    "reason": item.reason,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "error_message": item.error_message
                }
                for item in recent_items
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to get queue status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/queue/{queue_id}")
async def delete_queue_item(
    queue_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete an item from the extraction queue.
    
    Args:
        queue_id: Queue item ID
        
    Returns:
        Success message
    """
    try:
        queue_item = db.query(SOWExtractionQueue).filter(
            SOWExtractionQueue.id == queue_id
        ).first()
        
        if not queue_item:
            raise HTTPException(status_code=404, detail="Queue item not found")
        
        db.delete(queue_item)
        db.commit()
        
        return {
            "success": True,
            "message": f"Deleted queue item {queue_id}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete queue item {queue_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/process")
async def process_queue_batch(
    batch_size: int = 10,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Process a batch of queued SOW extractions.
    
    This endpoint triggers background processing of queued contracts.
    
    Args:
        batch_size: Number of items to process (default: 10, max: 50)
        
    Returns:
        Processing status
    """
    try:
        if batch_size > 50:
            batch_size = 50
        
        # Get pending items
        pending_items = db.query(SOWExtractionQueue).filter(
            SOWExtractionQueue.status == "PENDING"
        ).order_by(
            SOWExtractionQueue.priority.desc(),
            SOWExtractionQueue.created_at.asc()
        ).limit(batch_size).all()
        
        if not pending_items:
            return {
                "success": True,
                "message": "No pending items in queue",
                "processed": 0
            }
        
        # Process items in background
        if background_tasks:
            background_tasks.add_task(
                process_sow_queue_batch,
                [item.id for item in pending_items]
            )
            
            return {
                "success": True,
                "message": f"Started processing {len(pending_items)} items in background",
                "batch_size": len(pending_items)
            }
        else:
            return {
                "success": False,
                "message": "Background tasks not available",
                "batch_size": 0
            }
        
    except Exception as e:
        logger.error(f"Failed to process queue batch: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Background task function
async def process_sow_queue_batch(queue_ids: List[int]):
    """
    Background task to process a batch of SOW extractions.
    
    This runs asynchronously and processes each queued item.
    """
    from app.core.database import SessionLocal
    import json
    
    db = SessionLocal()
    sow_service = SOWService(db)
    
    try:
        for queue_id in queue_ids:
            try:
                # Get queue item
                queue_item = db.query(SOWExtractionQueue).filter(
                    SOWExtractionQueue.id == queue_id
                ).first()
                
                if not queue_item or queue_item.status != "PENDING":
                    continue
                
                # Mark as processing
                queue_item.status = "PROCESSING"
                db.commit()
                
                # TODO: Get contract attachments from your contracts data
                # For now, this is a placeholder - you'll need to fetch the actual contract
                # attachments from wherever you store them (database, API, etc.)
                
                # Example:
                # contract = get_contract_by_notice_id(queue_item.notice_id)
                # attachments = json.loads(contract.attachments) if contract.attachments else []
                
                # For now, mark as failed with helpful message
                queue_item.status = "FAILED"
                queue_item.error_message = "Attachment fetching not yet implemented - integrate with your contract storage"
                queue_item.processed_at = func.now()
                db.commit()
                
                logger.info(f"Processed queue item {queue_id} for {queue_item.notice_id}")
                
            except Exception as e:
                logger.error(f"Failed to process queue item {queue_id}: {str(e)}")
                if queue_item:
                    queue_item.status = "FAILED"
                    queue_item.error_message = str(e)
                    queue_item.processed_at = func.now()
                    db.commit()
        
    finally:
        await sow_service.close()
        db.close()