from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware.audit import AuditMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.api.routes import router
from app.api.debug_routes import debug_router
from app.auth.register import router as register_router
from app.auth.login import router as login_router
from app.database import init_db, engine
from app.routers import company
from contextlib import asynccontextmanager
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI.
    Handles startup and shutdown events.
    """
    # ========== STARTUP ==========
    logger.info("🚀 Starting FastAPI application...")
    
    email_scheduler = None
    csv_scheduler = None
    
    # Start the email scheduler
    try:
        from app.tasks.email_scheduler import email_scheduler
        email_scheduler.start()
        logger.info("✅ Email scheduler initialized and running")
    except Exception as e:
        logger.error(f"❌ Failed to start email scheduler: {e}")
    
    # Start the CSV contract sync service (non-blocking)
    try:
        from app.tasks.csv_sync import setup_scheduler
        import asyncio
        
        csv_scheduler = setup_scheduler()
        csv_scheduler.start()
        
        # Run initial sync in background AFTER startup completes
        async def background_initial_sync():
            try:
                await asyncio.sleep(10)  # Wait 10 seconds for app to fully start
                from app.tasks.csv_sync import sync_contracts_from_csv
                logger.info("🔄 Running initial CSV sync in background...")
                await sync_contracts_from_csv()
                logger.info("✅ Initial CSV sync complete")
            except Exception as e:
                logger.error(f"❌ Background CSV sync failed: {e}")
        
        # Fire and forget - don't await
        asyncio.create_task(background_initial_sync())
        logger.info("✅ CSV contract sync service initialized")
    except Exception as e:
        logger.error(f"❌ Failed to start CSV sync service: {e}")
    
    yield  # Application runs here
    
    # ========== SHUTDOWN ==========
    logger.info("🛑 Shutting down FastAPI application...")
    
    # Stop the email scheduler
    if email_scheduler:
        try:
            email_scheduler.shutdown()
            logger.info("✅ Email scheduler stopped")
        except Exception as e:
            logger.error(f"❌ Error stopping email scheduler: {e}")
    
    # Stop the CSV sync scheduler
    if csv_scheduler:
        try:
            csv_scheduler.shutdown()
            logger.info("✅ CSV sync scheduler stopped")
        except Exception as e:
            logger.error(f"❌ Error stopping CSV sync scheduler: {e}")


# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# CREATE APP INSTANCE
app = FastAPI(
    title="Contract Discovery API",
    description="Government contract matching platform with email notifications",
    version="1.0.0",
    lifespan=lifespan
)

# ========== CORS CONFIGURATION ==========
# Allow requests from your frontend domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Local development
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # Specific production domains
        "https://bidboost-ooaqyryk4-sunny-dilgeers-projects.vercel.app",
        "https://www.bidboost.ai",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",  # Regex for ALL Vercel deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Add audit logging middleware
app.add_middleware(AuditMiddleware)

# Add rate limiting middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ========== INCLUDE ROUTERS ==========
app.include_router(router)
app.include_router(register_router, prefix="/api/auth")
app.include_router(login_router, prefix="/api/auth")
app.include_router(company.router)
app.include_router(debug_router)

logger.info("✓ All routes registered")


@app.on_event("startup")
async def startup_event():
    """Initialize database and log startup information"""
    logger.info("=" * 60)
    logger.info("Contract Discovery API Starting...")
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
    logger.info("Contract Discovery API shutting down...")
    try:
        engine.dispose()
        logger.info("✓ Database connections closed")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")


# ========== ROOT ENDPOINTS ==========

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Contract Discovery API - Government Contract Matching",
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
        "service": "contract-discovery-api",
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
    
    # Check Ollama (optional - might not be used if using OpenAI)
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            services["llm"] = "ready" if response.status_code == 200 else "not ready"
    except Exception as e:
        services["llm"] = f"not ready: {str(e)}"
        logger.warning(f"Ollama readiness check failed (this is OK if using OpenAI): {e}")
    
    all_ready = all(status == "ready" for status in services.values())
    
    return {
        "status": "ready" if all_ready else "not ready",
        "services": services
    }


# ========== ADMIN ENDPOINTS ==========

@app.post("/admin/trigger-email-job/{job_id}", tags=["Admin"])
async def trigger_email_job(job_id: str):
    """
    Manually trigger an email job for testing.
    
    job_id options:
    - daily_contract_emails
    - deadline_reminders
    - sync_contracts_daily
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
        logger.error(f"Failed to trigger job {job_id}: {e}")
        return {
            "success": False,
            "error": f"Failed to trigger job: {str(e)}"
        }


@app.post("/admin/test-email", tags=["Admin"])
async def test_email_system():
    """
    Test email system - sends a test email to verify SendGrid setup.
    No authentication required for testing.
    """
    try:
        from app.services.email_service import email_service
        
        # Test SendGrid connection
        if not email_service.test_connection():
            return {
                "success": False,
                "error": "SendGrid API key not configured"
            }
        
        # Send test email (hardcoded for testing)
        test_contracts = [
            {
                "notice_id": "test-123",
                "title": "Test Contract - IT Services",
                "buyer_name": "Test Government Department",
                "value": "£50,000",
                "deadline": "2025-12-15",
                "match_score": 87,
                "match_reason": "This is a test email to verify your notification setup"
            }
        ]
        
        # Use a test email or get from environment
        import os
        test_email = os.getenv("TEST_EMAIL", "test@example.com")
        
        success = email_service.send_new_contracts_email(
            to_email=test_email,
            user_name="Test User",
            contracts=test_contracts,
            total_new_contracts=1
        )
        
        if success:
            return {
                "success": True,
                "message": f"Test email sent to {test_email}",
                "note": "Check your inbox (and spam folder)"
            }
        else:
            return {
                "success": False,
                "error": "Failed to send test email"
            }
    except Exception as e:
        logger.error(f"Email test failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@app.post("/admin/sync-contracts", tags=["Admin"])
async def trigger_contract_sync():
    """
    Manually trigger CSV contract sync for testing/admin use.
    
    This endpoint:
    - Downloads the latest CSV from Contracts Finder
    - Processes all open/active contracts
    - Upserts them to Qdrant vector store
    """
    try:
        from app.tasks.csv_sync import manual_sync
        result = await manual_sync()
        
        return {
            "success": result["status"] == "complete",
            "message": "Contract sync completed successfully" if result["status"] == "complete" else "Contract sync failed",
            "details": result
        }
    except Exception as e:
        logger.error(f"Manual sync endpoint error: {e}")
        return {
            "success": False,
            "message": f"Failed to trigger sync: {str(e)}",
            "details": None
        }


@app.get("/admin/sync-status", tags=["Admin"])
async def get_sync_status():
    """
    Get the status of the contract sync service.
    
    Returns information about:
    - Next scheduled sync time
    - Last sync result (if available)
    - Contract counts in Qdrant
    """
    try:
        from app.services.vector_store import VectorStoreService
        
        vector_store = VectorStoreService()
        contract_count = vector_store.get_document_count(document_type="contract_opportunity")
        
        return {
            "success": True,
            "contract_count": contract_count,
            "next_sync": "Daily at 7:00 AM UTC",
            "message": f"CSV sync service is running. {contract_count} contracts in database."
        }
    except Exception as e:
        logger.error(f"Sync status error: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to get sync status"
        }


@app.get("/admin/scheduler-status", tags=["Admin"])
async def get_scheduler_status():
    """Get status of email scheduler and its jobs"""
    try:
        from app.tasks.email_scheduler import email_scheduler
        
        jobs = []
        for job in email_scheduler.scheduler.get_jobs():
            next_run = email_scheduler.scheduler.get_job(job.id).next_run_time if email_scheduler.scheduler.get_job(job.id) else None
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(next_run) if next_run else "Not scheduled",
                "trigger": str(job.trigger)
            })
        
        return {
            "success": True,
            "scheduler_running": email_scheduler.scheduler.running,
            "jobs": jobs
        }
    except Exception as e:
        logger.error(f"Scheduler status error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ========== MAIN ENTRY POINT ==========

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        log_level="info"
    )