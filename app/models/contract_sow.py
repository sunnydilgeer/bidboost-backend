from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Index
from sqlalchemy.sql import func
from app.database import Base

class ContractSOW(Base):
    """
    Stores extracted Statement of Work text from contract attachments.
    Improves semantic matching when SAM.gov descriptions are garbage (e.g., "Amendment 003 posted").
    """
    __tablename__ = "contract_sows"
    
    id = Column(Integer, primary_key=True, index=True)
    notice_id = Column(String(255), unique=True, nullable=False, index=True)
    
    # Extracted SOW content
    sow_text = Column(Text, nullable=False)
    confidence = Column(String(20), nullable=False)  # HIGH | MEDIUM | LOW
    source_filename = Column(String(500))
    
    # Quality indicators
    word_count = Column(Integer)
    has_deliverables = Column(Boolean, default=False)
    has_tasks = Column(Boolean, default=False)
    extraction_method = Column(String(50))  # pdf_text | ocr | fallback
    
    # Metadata
    pdf_url = Column(Text)
    pdf_size_bytes = Column(Integer)
    extracted_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_sows_notice_id', 'notice_id'),
        Index('idx_sows_confidence', 'confidence'),
    )


class SOWExtractionQueue(Base):
    """
    Queue for background SOW extraction processing.
    Tracks which contracts need SOW extraction and their status.
    """
    __tablename__ = "sow_extraction_queue"
    
    id = Column(Integer, primary_key=True, index=True)
    notice_id = Column(String(255), nullable=False, index=True)
    
    # Priority and status
    priority = Column(String(20), default='MEDIUM')  # HIGH | MEDIUM | LOW
    status = Column(String(20), default='PENDING')   # PENDING | PROCESSING | COMPLETED | FAILED
    reason = Column(Text)  # Why it needs extraction
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    
    # Error tracking
    error_message = Column(Text)
    
    # Indexes
    __table_args__ = (
        Index('idx_queue_status', 'status'),
        Index('idx_queue_priority', 'priority'),
        Index('idx_queue_created_at', 'created_at'),
    )