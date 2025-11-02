from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Conversation, Message, User as DBUser
from app.core.auth import get_current_user, User as AuthUser
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import uuid as uuid_lib

router = APIRouter(prefix="/conversations", tags=["conversations"])  # ✅ Removed /api

# Pydantic models
class ConversationCreate(BaseModel):
    title: Optional[str] = None

class ConversationResponse(BaseModel):
    id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    message_count: Optional[int] = 0

class MessageCreate(BaseModel):
    role: str
    content: str
    sources: Optional[List[dict]] = None

class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sources: Optional[List[dict]]
    timestamp: datetime

# Endpoints
@router.post("", response_model=ConversationResponse)
async def create_conversation(
    conversation: ConversationCreate,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new conversation"""
    # Get database user by ID (not email)
    db_user = db.query(DBUser).filter(DBUser.id == current_user.user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found in database")
    
    new_conv = Conversation(
        id=str(uuid_lib.uuid4()),  # Generate UUID for conversation
        user_id=db_user.id,
        firm_id=db_user.firm_id,
        title=conversation.title or "New Conversation"
    )
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)
    
    return ConversationResponse(
        id=str(new_conv.id),
        title=new_conv.title,
        created_at=new_conv.created_at,
        updated_at=new_conv.updated_at,
        message_count=0
    )

@router.get("", response_model=List[ConversationResponse])
async def list_conversations(
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all conversations for the current user"""
    db_user = db.query(DBUser).filter(DBUser.id == current_user.user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found in database")
    
    conversations = db.query(Conversation).filter(
        Conversation.firm_id == db_user.firm_id,
        Conversation.user_id == db_user.id
    ).order_by(Conversation.updated_at.desc()).all()
    
    return [
        ConversationResponse(
            id=str(conv.id),
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=len(conv.messages)
        )
        for conv in conversations
    ]

@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: str,  # Changed from UUID to str
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all messages in a conversation"""
    db_user = db.query(DBUser).filter(DBUser.id == current_user.user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found in database")
    
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.firm_id == db_user.firm_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return [
        MessageResponse(
            id=str(msg.id),
            role=msg.role,
            content=msg.content,
            sources=msg.sources,
            timestamp=msg.timestamp
        )
        for msg in conversation.messages
    ]

@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def add_message(
    conversation_id: str,  # Changed from UUID to str
    message: MessageCreate,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a message to a conversation"""
    db_user = db.query(DBUser).filter(DBUser.id == current_user.user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found in database")
    
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.firm_id == db_user.firm_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    new_message = Message(
        id=str(uuid_lib.uuid4()),  # Generate UUID for message
        conversation_id=conversation_id,
        role=message.role,
        content=message.content,
        sources=message.sources
    )
    db.add(new_message)
    
    conversation.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(new_message)
    
    return MessageResponse(
        id=str(new_message.id),
        role=new_message.role,
        content=new_message.content,
        sources=new_message.sources,
        timestamp=new_message.timestamp
    )