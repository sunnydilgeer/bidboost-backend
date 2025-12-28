from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Force load .env from project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path, override=True)

class Settings(BaseSettings):
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    ENVIRONMENT: str = "development"
    API_SECRET_KEY: str = "dev-secret-key-change-in-production"
    
    # Database Configuration
    DATABASE_URL: str = "postgresql://legal_rag_user:secure_password@127.0.0.1:5432/legal_rag_db"
    
    # Qdrant Configuration
    QDRANT_COLLECTION_NAME: str = "legal_documents"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    
    # Ollama Configuration (for local dev)
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_URL: str = "http://localhost:11434"
    
    # OpenAI Configuration (for production embeddings)
    USE_OPENAI_EMBEDDINGS: bool = True
    OPENAI_API_KEY: Optional[str] = "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"
    
    # JWT/Auth Configuration
    JWT_SECRET: str = "your-super-secure-secret-key-change-this-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    SENDGRID_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@yourapp.com"
    FRONTEND_URL: str = "http://localhost:3000"
    PINECONE_API_KEY: Optional[str] = None
    USE_PINECONE: bool = False
    PINECONE_INDEX_NAME: str = "contracts"
    SAM_API_KEY: Optional[str] = None  
    
    # Stripe Configuration
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRO_PRICE_ID: str
    STRIPE_STARTER_PRICE_ID: str  # ✅ NEW - Add this line
    RESEND_API_KEY: Optional[str] = None  # ← Add this

    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()