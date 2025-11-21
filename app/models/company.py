# app/models/company.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, ForeignKey, Numeric, Date, JSON, Index, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum

class CompanySize(enum.Enum):
    MICRO = "micro"  # < 10 employees
    SMALL = "small"  # 10-49
    MEDIUM = "medium"  # 50-249
    LARGE = "large"  # 250+

class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    firm_id = Column(String(255), nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    registration_number = Column(String(50), nullable=True)
    size = Column(SQLEnum(CompanySize), nullable=False)
    founded_year = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    
    # 🆕 Onboarding tracking fields
    onboarding_completed = Column(Integer, default=0, nullable=False)  # 0=not started, 1=in progress, 2=completed
    onboarding_step = Column(Integer, default=0, nullable=False)  # Current step 0-4
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # 🆕 US FEDERAL-SPECIFIC FIELDS
    # Set-aside certifications (critical for eligibility)
    sba_certified = Column(Boolean, default=False, nullable=False)  # Small Business Administration
    sdvosb_certified = Column(Boolean, default=False, nullable=False)  # Service-Disabled Veteran-Owned
    wosb_certified = Column(Boolean, default=False, nullable=False)  # Women-Owned Small Business
    hubzone_certified = Column(Boolean, default=False, nullable=False)  # Historically Underutilized Business Zone
    eight_a_certified = Column(Boolean, default=False, nullable=False)  # 8(a) Business Development Program
    
    # Industry classification codes
    naics_codes = Column(JSON, default=list)  # North American Industry Classification System
    psc_codes = Column(JSON, default=list)  # Product Service Codes (federal procurement)
    
    # Federal contracting identifiers
    cage_code = Column(String(50), nullable=True)  # Commercial and Government Entity Code
    uei_number = Column(String(50), nullable=True)  # Unique Entity Identifier (replaces DUNS)
    sam_registered = Column(Boolean, default=False, nullable=False)  # Registered in SAM.gov
    sam_expiration = Column(Date, nullable=True)  # SAM.gov registration expiration
    
    # Past performance tracking
    federal_experience = Column(Boolean, default=False, nullable=False)  # Has federal contract experience
    federal_contracts_count = Column(Integer, default=0)  # Number of federal contracts won
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    capabilities = relationship("CompanyCapability", back_populates="company", cascade="all, delete-orphan")
    past_wins = relationship("PastWin", back_populates="company", cascade="all, delete-orphan")
    search_preference = relationship("SearchPreference", back_populates="company", uselist=False, cascade="all, delete-orphan")


class CompanyCapability(Base):
    __tablename__ = "company_capabilities"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    capability_text = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    years_experience = Column(Integer, nullable=True)
    
    # 🆕 US Federal-specific
    naics_code = Column(String(10), nullable=True)  # Associated NAICS code for this capability
    security_clearance = Column(String(50), nullable=True)  # e.g., "Secret", "Top Secret", "Public Trust"
    
    qdrant_id = Column(String(100), nullable=True, index=True)  # Vector DB reference
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    company = relationship("CompanyProfile", back_populates="capabilities")


class PastWin(Base):
    __tablename__ = "past_wins"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_title = Column(String(500), nullable=False)
    buyer_name = Column(String(255), nullable=False)
    contract_value = Column(Numeric(15, 2), nullable=True)
    award_date = Column(Date, nullable=False)
    contract_duration_months = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    
    # 🆕 US Federal-specific
    contract_number = Column(String(100), nullable=True)  # Federal contract number
    naics_code = Column(String(10), nullable=True)  # NAICS code of the contract
    federal_contract = Column(Boolean, default=False)  # Was this a federal contract?
    agency_name = Column(String(255), nullable=True)  # Specific federal agency
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    company = relationship("CompanyProfile", back_populates="past_wins")


class SearchPreference(Base):
    __tablename__ = "search_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    min_contract_value = Column(Numeric(15, 2), nullable=True)
    max_contract_value = Column(Numeric(15, 2), nullable=True)
    preferred_regions = Column(JSON, default=list)  # US states (e.g., ["CA", "TX", "DC"])
    excluded_categories = Column(JSON, default=list)
    keywords = Column(JSON, default=list)
    
    # 🆕 US Federal-specific preferences
    preferred_agencies = Column(JSON, default=list)  # e.g., ["DOD", "DHS", "GSA"]
    preferred_set_asides = Column(JSON, default=list)  # e.g., ["SBA", "SDVOSB"]
    excluded_naics = Column(JSON, default=list)  # NAICS codes to exclude
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    company = relationship("CompanyProfile", back_populates="search_preference")


class ContractStatus(str, enum.Enum):
    INTERESTED = "interested"
    BIDDING = "bidding"
    WON = "won"
    LOST = "lost"


class SavedContract(Base):
    __tablename__ = "saved_contracts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String(255), nullable=False, index=True)
    firm_id = Column(String(255), nullable=False, index=True)
    
    # Contract reference
    notice_id = Column(String(255), nullable=False, index=True)
    contract_title = Column(String(500), nullable=False)
    buyer_name = Column(String(255), nullable=False)
    contract_value = Column(Numeric(15, 2), nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)
    
    # Saved contract metadata
    status = Column(String(50), default="interested", nullable=False)
    notes = Column(Text, nullable=True)
    saved_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_user_contract', 'user_email', 'notice_id', unique=True),
    )