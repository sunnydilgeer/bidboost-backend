from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
import os
import uuid

from app.database import get_db
from app.models import User as DBUser

# Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Pydantic Models for API
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    firm_id: str

class User(BaseModel):
    user_id: str
    email: str
    full_name: str
    firm_id: str
    role: str = "user"
    is_active: bool = True

class TokenData(BaseModel):
    email: str
    firm_id: str
    role: str

# Password utilities
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# Database operations
def get_user_by_email(db: Session, email: str) -> Optional[DBUser]:
    """Retrieve user from PostgreSQL by email"""
    return db.query(DBUser).filter(DBUser.email == email).first()

def get_user_by_id(db: Session, user_id: str) -> Optional[DBUser]:
    """Retrieve user from PostgreSQL by UUID"""
    return db.query(DBUser).filter(DBUser.id == user_id).first()

def create_user(db: Session, email: str, password: str, firm_id: str, full_name: str) -> DBUser:
    """Create new user in PostgreSQL"""
    # Check if user already exists
    existing_user = get_user_by_email(db, email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    hashed_password = hash_password(password)
    db_user = DBUser(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=hashed_password,
        firm_id=firm_id,
        full_name=full_name,
        role="user",
        is_active=True
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, email: str, password: str) -> Optional[DBUser]:
    """Verify user credentials against PostgreSQL"""
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    return user

# JWT token creation
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# FastAPI dependency for protected routes
async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Extract and validate user from JWT token, verify against database"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode JWT
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_id: str = payload.get("user_id")
        firm_id: str = payload.get("firm_id")
        
        if email is None or user_id is None:
            raise credentials_exception
        
        # Verify user still exists in database
        db_user = get_user_by_id(db, user_id)
        if db_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User no longer exists"
            )
        
        if not db_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        
        # Create Pydantic user object
        user = User(
            user_id=db_user.id,
            email=db_user.email,
            full_name=db_user.full_name,
            firm_id=db_user.firm_id,
            role=db_user.role,
            is_active=db_user.is_active
        )
        
        # Set user info on request state for audit middleware
        request.state.user_id = user.user_id
        request.state.firm_id = user.firm_id
        
        return user
        
    except JWTError:
        raise credentials_exception

async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Additional layer for checking active status (already done in get_current_user)"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user