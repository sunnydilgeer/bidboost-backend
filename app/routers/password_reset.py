from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timedelta
from app.database import get_db
from app.models import User
from app.core.auth import hash_password
import secrets

router = APIRouter(tags=["Password Reset"])

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)

@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Send password reset email"""
    user = db.query(User).filter(User.email == request.email).first()
    
    # Always return success to prevent email enumeration
    if not user:
        return {"message": "If that email exists, we've sent reset instructions"}
    
    # Generate secure token (valid for 1 hour)
    reset_token = secrets.token_urlsafe(32)
    user.reset_token = reset_token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    
    # TODO: Send email with reset link
    # For now, print for testing
    reset_url = f"https://bidmatch.co/reset-password?token={reset_token}"    
    print(f"🔐 Password Reset URL: {reset_url}")
    
    return {"message": "If that email exists, we've sent reset instructions"}

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using token"""
    user = db.query(User).filter(
        User.reset_token == request.token,
        User.reset_token_expires > datetime.utcnow()
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Update password using your existing hash_password function
    user.hashed_password = hash_password(request.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    db.commit()
    
    return {"message": "Password reset successful"}