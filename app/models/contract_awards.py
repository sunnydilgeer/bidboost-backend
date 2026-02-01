# app/models/contract_awards.py

from sqlalchemy import Column, Integer, String, Text, DateTime, Numeric, Date, Index, Boolean
from sqlalchemy.sql import func
from app.database import Base

class ContractAward(Base):
    """
    Historical contract awards from USASpending.gov.
    Used for incumbent tracking, pricing benchmarks, and competition analysis.
    """
    __tablename__ = "contract_awards"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Award identifiers
    award_id = Column(String(255), unique=True, nullable=False, index=True)
    piid = Column(String(255), nullable=True, index=True)
    
    # Awardee (THE INCUMBENT!)
    awardee_name = Column(String(255), nullable=False, index=True)
    awardee_uei = Column(String(50), nullable=True)
    awardee_duns = Column(String(50), nullable=True)
    
    # Agency info
    agency_name = Column(String(255), nullable=False, index=True)
    sub_agency_name = Column(String(255), nullable=True)
    office_name = Column(Text, nullable=True)
    
    # Classification
    naics_code = Column(String(10), nullable=True, index=True)
    naics_description = Column(Text, nullable=True)
    psc_code = Column(String(10), nullable=True, index=True)
    psc_description = Column(Text, nullable=True)
    
    # Award details
    award_amount = Column(Numeric(15, 2), nullable=True)
    contract_start_date = Column(Date, nullable=True)
    contract_end_date = Column(Date, nullable=True, index=True)
    award_date = Column(Date, nullable=True)
    
    # Competition data
    number_of_offers = Column(Integer, nullable=True)
    extent_competed = Column(String(100), nullable=True)
    set_aside_type = Column(String(100), nullable=True)
    
    # Contract type
    contract_type = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    
    # Place of performance
    pop_state = Column(String(50), nullable=True)
    pop_city = Column(String(100), nullable=True)
    pop_country = Column(String(100), nullable=True)
    
    # Tracking
    fiscal_year = Column(Integer, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_agency_naics', 'agency_name', 'naics_code'),
        Index('idx_awardee_agency', 'awardee_name', 'agency_name'),
        Index('idx_end_date_active', 'contract_end_date', 'is_active'),
    )