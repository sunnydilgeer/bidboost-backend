from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware.audit import AuditMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.api.routes import router, debug_router
from app.auth.register import router as register_router
from app.auth.login import router as login_router
from app.database import init_db, engine
from app.routers import company
from contextlib import asynccontextmanager

import logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI.
    Handles startup and shutdown events.
    """
    # ========== STARTUP ==========
    logger.info("🚀 Starting FastAPI application...")
    
    # Start the email scheduler
    try:
        from app.tasks.email_scheduler import email_scheduler
        email_scheduler.start()
        logger.info("✅ Email scheduler initialized and running")
    except Exception as e:
        logger.error(f"❌ Failed to start email scheduler: {e}")
    
    yield  # Application runs here
    
    # ========== SHUTDOWN ==========
    logger.info("🛑 Shutting down FastAPI application...")
    
    # Stop the scheduler gracefully
    try:
        from app.tasks.email_scheduler import email_scheduler
        email_scheduler.shutdown()
        logger.info("✅ Email scheduler stopped")
    except Exception as e:
        logger.error(f"❌ Error stopping email scheduler: {e}")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# CREATE APP INSTANCE FIRST
app = FastAPI(
    title="Contract Discovery API",
    description="Government contract matching platform with email notifications",
    version="1.0.0",
    lifespan=lifespan  
)

# CORS middleware - configured for development and production
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://bidboost-mkjdofs0x-sunny-dilgeers-projects.vercel.app",
    "https://*.vercel.app",  # Allow all Vercel preview deployments
    "*",  # Temporarily allow all for testing
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Add audit logging middleware (BEFORE routes, AFTER CORS)
app.add_middleware(AuditMiddleware)

# Add rate limiting middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Include all API routes
app.include_router(router)  # Main API routes (query, ingest, conversations, etc.)
app.include_router(register_router, prefix="/api/auth")  # Registration endpoint
app.include_router(login_router, prefix="/api/auth")  # Login endpoint
app.include_router(company.router)  # Company profile routes
app.include_router(debug_router)  # ✅ Keep this here

# 🆕 ADD DEBUG ROUTER (after app is created, with error handling)
logger.info("✓ Debug routes registered at /api/debug")

@app.on_event("startup")
async def startup_event():
    """Initialize database and log startup information"""
    logger.info("=" * 60)
    logger.info("Legal RAG API Starting...")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"API Host: {settings.API_HOST}:{settings.API_PORT}")
    
    # Initialize PostgreSQL database
    try:
        logger.info("Initializing PostgreSQL database...")
        init_db()
        logger.info("✓ Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"✗ Database initialization failed: {e}")
        logger.warning("API will start but database operations may fail")
    
    logger.info(f"Docs available at: http://{settings.API_HOST}:{settings.API_PORT}/docs")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Legal RAG API shutting down...")
    try:
        engine.dispose()
        logger.info("✓ Database connections closed")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Legal RAG API - Document Intelligence for UK Law Firms",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "status": "operational"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    from sqlalchemy import text
    
    # Check database connection
    db_status = "healthy"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        logger.error(f"Database health check failed: {e}")
    
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "service": "legal-rag-api",
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
        "database": db_status
    }

@app.get("/ready")
async def readiness_check():
    """Readiness check - verifies all services are ready"""
    from sqlalchemy import text
    import httpx
    
    services = {
        "api": "ready",
        "database": "unknown",
        "vector_db": "unknown",
        "llm": "unknown"
    }
    
    # Check PostgreSQL
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        services["database"] = "ready"
    except Exception as e:
        services["database"] = f"not ready: {str(e)}"
        logger.error(f"PostgreSQL readiness check failed: {e}")
    
    # Check Qdrant
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.QDRANT_URL}/health")
            services["vector_db"] = "ready" if response.status_code == 200 else "not ready"
    except Exception as e:
        services["vector_db"] = f"not ready: {str(e)}"
        logger.error(f"Qdrant readiness check failed: {e}")
    
    # Check Ollama
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            services["llm"] = "ready" if response.status_code == 200 else "not ready"
    except Exception as e:
        services["llm"] = f"not ready: {str(e)}"
        logger.error(f"Ollama readiness check failed: {e}")
    
    all_ready = all(status == "ready" for status in services.values())
    
    return {
        "status": "ready" if all_ready else "not ready",
        "services": services
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        log_level="info"
    )

@app.post("/admin/trigger-email-job/{job_id}", tags=["Admin"])
async def trigger_email_job(job_id: str):
    """
    Manually trigger an email job for testing.
    
    job_id options:
    - daily_contract_emails
    - deadline_reminders
    """
    try:
        from app.tasks.email_scheduler import email_scheduler
        email_scheduler.run_job_now(job_id)
        return {
            "success": True,
            "message": f"Job '{job_id}' triggered successfully",
            "note": "Check server logs for execution status"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to trigger job: {str(e)}"
        }