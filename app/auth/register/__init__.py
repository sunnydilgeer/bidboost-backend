from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from app.core.auth import create_user, create_access_token
from app.database import get_db

router = APIRouter(tags=["Authentication"])

# Updated UserCreate model to accept firm_name
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str
    firm_name: str  # User-friendly firm name instead of firm_id

@router.post("/register")
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user - writes to PostgreSQL"""
    try:
        # Auto-generate firm_id from firm_name
        firm_id = f"firm-{user_data.firm_name.lower().replace(' ', '-').replace('_', '-')}"
        
        # Create user in database
        db_user = create_user(
            db=db,
            email=user_data.email,
            password=user_data.password,
            firm_id=firm_id,  # Auto-generated ID
            full_name=user_data.full_name
        )
        
        # Store the user-friendly firm name in the database
        db_user.firm_name = user_data.firm_name
        db.commit()
        db.refresh(db_user)
        
        # Create JWT token
        access_token = create_access_token(
            data={
                "sub": db_user.email,
                "user_id": db_user.id,
                "firm_id": db_user.firm_id,
                "role": db_user.role,
                "name": db_user.full_name
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