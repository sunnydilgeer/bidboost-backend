from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from typing import Optional  # ✅ add
from app.core.auth import create_user, create_access_token
from app.core.entitlements import get_or_create_subscription
from app.database import get_db
from app.services.email_service import email_service  # ✅ add (adjust import path)

router = APIRouter(tags=["Authentication"])


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str
    firm_name: str
    source: Optional[str] = None  # ✅ add (e.g. "quickstart" or "signup")


@router.post("/register")
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user - writes to PostgreSQL"""
    try:
        firm_id = f"firm-{user_data.firm_name.lower().replace(' ', '-').replace('_', '-')}"
        
        db_user = create_user(
            db=db,
            email=user_data.email,
            password=user_data.password,
            firm_id=firm_id,
            full_name=user_data.full_name
        )
        
        db_user.firm_name = user_data.firm_name
        db.commit()
        db.refresh(db_user)
        
        subscription = get_or_create_subscription(db, db_user.firm_id)

        # ✅ Send welcome email (do NOT block signup)
        try:
            from_quickstart = (user_data.source == "quickstart")
            email_service.send_welcome_email(
                to_email=db_user.email,
                user_name=db_user.full_name or db_user.firm_name or "there",
                from_quickstart=from_quickstart,
            )
        except Exception as email_err:
            # Don't fail signup if email fails
            print(f"Welcome email failed for {db_user.email}: {email_err}")

        access_token = create_access_token(
            data={
                "sub": db_user.email,
                "user_id": db_user.id,
                "firm_id": db_user.firm_id,
                "role": db_user.role,
                "name": db_user.full_name,
                "plan": subscription.plan
            }
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "user_id": db_user.id,
                "email": db_user.email,
                "full_name": db_user.full_name,
                "firm_id": db_user.firm_id,
                "firm_name": db_user.firm_name
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )