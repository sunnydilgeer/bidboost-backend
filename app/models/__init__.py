"""
Models package - All SQLAlchemy models
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Index, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

# ========== USER MODELS (defined here) ==========

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    firm_id = Column(String(255), nullable=False, index=True)
    firm_name = Column(String(255), nullable=True)
    role = Column(String(50), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    email_notifications_enabled = Column(Boolean, default=True, nullable=False)
    notification_frequency = Column(String(20), default="daily", nullable=False)
    last_email_sent_at = Column(DateTime, nullable=True)

    # Relationships
    audit_logs = relationship("AuditLog", back_populates="user")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    firm_id = Column(String(255), nullable=True, index=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), index=True)
    resource_id = Column(String(100))
    details = Column(JSONB)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    user = relationship("User", back_populates="audit_logs")
    
    __table_args__ = (
        Index('idx_audit_firm_timestamp', 'firm_id', 'timestamp'),
        Index('idx_audit_user_action', 'user_id', 'action'),
    )


class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    firm_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500))
    meta = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_conv_firm_updated', 'firm_id', 'updated_at'),
    )


class Message(Base):
    __tablename__ = "messages"
    
    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSONB)
    tokens_used = Column(Integer)
    latency_ms = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    conversation = relationship("Conversation", back_populates="messages")
    
    __table_args__ = (
        Index('idx_msg_conversation_timestamp', 'conversation_id', 'timestamp'),
    )


# ========== IMPORT MODELS FROM OTHER FILES ==========

from app.models.company import (
    CompanyProfile,
    CompanyCapability,
    PastWin,
    SearchPreference,
    SavedContract
)

from app.models.lead import PreSignupLead

# ========== EXPORT ALL MODELS ==========

__all__ = [
    # User models (defined above)
    "User",
    "AuditLog",
    "Conversation",
    "Message",
    
    # Company models (imported from company.py)
    "CompanyProfile",
    "CompanyCapability",
    "PastWin",
    "SearchPreference",
    "SavedContract",
    
    # Lead capture (imported from lead.py)
    "PreSignupLead"
]