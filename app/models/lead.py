"""
Pre-signup lead capture model for quickstart email reports
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.database import Base


class PreSignupLead(Base):
    __tablename__ = "pre_signup_leads"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    website_url = Column(String(500), nullable=False)
    quickstart_id = Column(String(100), nullable=False, index=True)
    source = Column(String(50), default="quickstart_report", nullable=False)
    
    # Store the quickstart summary data
    capabilities_text = Column(Text, nullable=True)
    quickstart_summary = Column(JSON, nullable=True)  # Stores company_name, total_matches, etc.
    
    # Tracking
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Conversion tracking
    converted_to_user = Column(String(255), nullable=True)  # Email of user account if they sign up
    converted_at = Column(DateTime(timezone=True), nullable=True)