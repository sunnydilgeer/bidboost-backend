from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Contract(BaseModel):
    """
    Lightweight contract model for match scoring.
    Contracts are stored in Qdrant, not PostgreSQL.
    This model is used to pass contract data to the scoring algorithm.
    """
    notice_id: str
    title: str
    description: Optional[str] = None
    buyer_name: str
    contract_value: Optional[float] = None
    region: Optional[str] = None
    qdrant_id: Optional[str] = None  # Vector DB reference for semantic search
    published_date: Optional[datetime] = None
    closing_date: Optional[datetime] = None
    cpv_codes: Optional[list[str]] = None
    
    class Config:
        from_attributes = True