from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from datetime import timedelta
from app.core.auth import authenticate_user, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.core.entitlements import get_or_create_subscription  # ✅ ADDED
from app.database import get_db

router = APIRouter(tags=["Authentication"])

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

@router.post("/login")
async def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    """Login user - validates against PostgreSQL"""
    user = authenticate_user(db, credentials.email, credentials.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ✅ ADDED: Get user's current plan
    subscription = get_or_create_subscription(db, user.firm_id)
    
    # Create JWT token with plan included
    access_token = create_access_token(
        data={
            "sub": user.email,
            "user_id": user.id,
            "firm_id": user.firm_id,
            "role": user.role,
            "name": user.full_name,
            "plan": subscription.plan  # ✅ ADDED
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "firm_id": user.firm_id
        }
    }