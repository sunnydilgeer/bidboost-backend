from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timedelta
from app.database import get_db
from app.models import User
from app.core.auth import hash_password
import secrets
import resend
import os

router = APIRouter(tags=["Password Reset"])

# Configure Resend
resend.api_key = os.getenv("RESEND_API_KEY")

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
    
    # Send email via Resend
    reset_url = f"https://bidmatch.co/reset-password?token={reset_token}"
    
    try:
        resend.Emails.send({
            "from": "BidMatch <onboarding@resend.dev>",  # Use Resend's test domain for now
            "to": request.email,
            "subject": "Reset Your BidMatch Password",
            "html": f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #2563eb;">Reset Your Password</h2>
                    <p>Hi {user.full_name},</p>
                    <p>We received a request to reset your password for your BidMatch account.</p>
                    <p>Click the button below to reset your password:</p>
                    <a href="{reset_url}" 
                       style="display: inline-block; background-color: #2563eb; color: white; 
                              padding: 12px 24px; text-decoration: none; border-radius: 8px; 
                              margin: 20px 0;">
                        Reset Password
                    </a>
                    <p>Or copy and paste this link into your browser:</p>
                    <p style="color: #666; word-break: break-all;">{reset_url}</p>
                    <p style="color: #666; font-size: 14px; margin-top: 30px;">
                        This link will expire in 1 hour.<br>
                        If you didn't request this, you can safely ignore this email.
                    </p>
                    <p style="color: #666; font-size: 12px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 20px;">
                        BidMatch - Government Contract Discovery Platform
                    </p>
                </div>
            """
        })
        print(f"✅ Password reset email sent to {request.email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        # Still return success to prevent email enumeration
    
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
