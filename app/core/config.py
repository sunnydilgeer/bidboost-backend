from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    ENVIRONMENT: str = "development"
    API_SECRET_KEY: str = "dev-secret-key-change-in-production"
    
    # Database Configuration
    DATABASE_URL: str = "postgresql://legal_rag_user:secure_password@127.0.0.1:5432/legal_rag_db"
    
    # Qdrant Configuration
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION_NAME: str = "legal_documents"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None  # Add this line
    
    # Ollama Configuration
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_URL: str = "http://localhost:11434"
    
    # JWT/Auth Configuration
    JWT_SECRET: str = "your-super-secure-secret-key-change-this-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    SENDGRID_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@yourapp.com"
    FRONTEND_URL: str = "http://localhost:3000"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
