# app/models/company.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, ForeignKey, Numeric, Date, JSON, Index
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
    firm_id = Column(String(255), nullable=False, index=True)  # Match User.firm_id type, no FK
    company_name = Column(String(255), nullable=False)
    registration_number = Column(String(50), nullable=True)
    size = Column(SQLEnum(CompanySize), nullable=False)
    founded_year = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
 # 🆕 Onboarding tracking fields
    onboarding_completed = Column(Integer, default=0, nullable=False)  # 0=not started, 1=in progress, 2=completed
    onboarding_step = Column(Integer, default=0, nullable=False)  # Current step 0-4
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    
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
    qdrant_id = Column(String(100), nullable=True, index=True)  # Vector DB reference for semantic search
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    company = relationship("CompanyProfile", back_populates="past_wins")

class SearchPreference(Base):
    __tablename__ = "search_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    min_contract_value = Column(Numeric(15, 2), nullable=True)
    max_contract_value = Column(Numeric(15, 2), nullable=True)
    preferred_regions = Column(JSON, default=list)
    excluded_categories = Column(JSON, default=list)
    keywords = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    company = relationship("CompanyProfile", back_populates="search_preference")


class ContractStatus(str, enum.Enum):
    INTERESTED = "interested"
    BIDDING = "bidding"
    WON = "won"
    LOST = "lost"

class SavedContract(Base):
    __tablename__ = "saved_contracts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String(255), nullable=False, index=True)  # Using email as user_id
    firm_id = Column(String(255), nullable=False, index=True)  # For future multi-user firm features
    
    # Contract reference (stored in Qdrant, not PostgreSQL)
    notice_id = Column(String(255), nullable=False, index=True)
    contract_title = Column(String(500), nullable=False)
    buyer_name = Column(String(255), nullable=False)
    contract_value = Column(Numeric(15, 2), nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)
    
    # Saved contract metadata
    status = Column(String(50), default="interested", nullable=False)
    notes = Column(Text, nullable=True)  # User's private notes
    saved_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Unique constraint: one user can only save a contract once
    __table_args__ = (
        Index('idx_user_contract', 'user_email', 'notice_id', unique=True),
    )
