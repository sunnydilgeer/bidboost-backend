from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL connection
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://legal_rag_user:secure_password@localhost:5432/legal_rag_db"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before using
    echo=False  # Set to True to see SQL queries
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """Dependency for FastAPI routes to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Create all database tables (dev only; prod uses Alembic)"""
    import app.models  # register models

    env = os.getenv("ENVIRONMENT", "development").lower()
    if env in ("prod", "production"):
        return  # Don't create tables in prod

    Base.metadata.create_all(bind=engine)