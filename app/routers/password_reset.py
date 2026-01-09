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
    
    if not user:
        return {"message": "If that email exists, we've sent reset instructions"}
    
    # Generate secure token
    reset_token = secrets.token_urlsafe(32)
    user.reset_token = reset_token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    
    # ✅ Use environment variable for frontend URL
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    reset_url = f"{frontend_url}/reset-password?token={reset_token}"
    
    try:
        resend.Emails.send({
            "from": "BidMatch <noreply@bidmatch.co>",
            "to": request.email,
            "subject": "Reset Your BidMatch Password",
            "html": f"""
                <!-- email template -->
                <a href="{reset_url}">Reset Password</a>
                <!-- ... -->
            """
        })
        print(f"✅ Password reset email sent to {request.email}")
        print(f"   Reset URL: {reset_url}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
    
    return {"message": "If that email exists, we've sent reset instructions"}

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using token"""
    print(f"🔍 Reset password request:")
    print(f"   Token: {request.token}")
    print(f"   Password length: {len(request.new_password)}")
    
    # Check if token exists at all
    user_with_token = db.query(User).filter(User.reset_token == request.token).first()
    print(f"   User with token found: {user_with_token is not None}")
    
    if user_with_token:
        print(f"   Token expires at: {user_with_token.reset_token_expires}")
        print(f"   Current time: {datetime.utcnow()}")
        print(f"   Token expired: {user_with_token.reset_token_expires <= datetime.utcnow()}")
    
    user = db.query(User).filter(
        User.reset_token == request.token,
        User.reset_token_expires > datetime.utcnow()
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Update password
    user.hashed_password = hash_password(request.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    db.commit()
    
    return {"message": "Password reset successful"}
