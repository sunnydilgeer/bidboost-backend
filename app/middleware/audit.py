from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.database import SessionLocal
from app.models import AuditLog
import time
import logging

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Audit middleware that logs API requests to the database.
    Skips high-frequency endpoints and health checks to prevent log spam.
    """
    
    # Endpoints that should NEVER be audited (webhooks, health checks, docs)
    SKIP_PATHS = {
        # Webhooks (require raw body)
        "/api/billing/webhook",
        "/api/api/billing/webhook",
        
        # Health & monitoring
        "/health",
        "/ready",
        "/favicon.ico",
        
        # Documentation
        "/docs",
        "/redoc",
        "/openapi.json",
        
        # High-frequency read endpoints (prevents polling spam)
        "/api/company/profile",
        "/api/contracts/saved",
        "/api/contracts/recommended",
        "/api/admin/pinecone-status",
    }
    
    # Resource type mappings
    RESOURCE_MAPPINGS = {
        "auth": ["auth"],
        "document": ["documents"],
        "query": ["query"],
        "conversation": ["conversations"],
        "billing": ["billing"],
        "contract": ["contracts"],
        "company": ["company"],
    }
    
    # Action mappings for specific endpoints
    ACTION_MAPPINGS = {
        "/auth/login": "user_login",
        "/auth/register": "user_register",
        "/auth/logout": "user_logout",
        "/documents/upload": "document_upload",
        "/contracts/save": "contract_save",
        "/contracts/search": "contract_search",
    }

    async def dispatch(self, request: Request, call_next):
        """Main middleware handler"""
        path = request.url.path
        method = request.method

        # Skip paths that shouldn't be audited
        if self._should_skip_audit(path):
            return await call_next(request)

        # Extract user context
        user_id = getattr(request.state, "user_id", None)
        firm_id = getattr(request.state, "firm_id", None)

        # Process request and measure latency
        start_time = time.time()
        response = await call_next(request)
        latency_ms = int((time.time() - start_time) * 1000)

        # Log to database (async, non-blocking)
        try:
            self._save_audit_log(
                user_id=user_id,
                firm_id=firm_id,
                method=method,
                path=path,
                status_code=response.status_code,
                latency_ms=latency_ms,
                ip_address=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("user-agent", ""),
            )
        except Exception as e:
            # Don't let audit failures break the request
            logger.error(f"Audit logging failed for {method} {path}: {e}", exc_info=True)

        return response

    def _should_skip_audit(self, path: str) -> bool:
        """Check if path should be skipped from auditing"""
        return any(path.startswith(skip_path) for skip_path in self.SKIP_PATHS)

    def _save_audit_log(
        self,
        user_id: str | None,
        firm_id: str | None,
        method: str,
        path: str,
        status_code: int,
        latency_ms: int,
        ip_address: str,
        user_agent: str,
    ) -> None:
        """Save audit log entry to database"""
        db = None
        try:
            db = SessionLocal()
            
            audit_entry = AuditLog(
                user_id=user_id,
                firm_id=firm_id,
                action=self._determine_action(method, path),
                resource_type=self._extract_resource_type(path),
                details={
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "user_email": user_id,  # user_id is the email
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            
            db.add(audit_entry)
            db.commit()
            
        except Exception as e:
            logger.error(f"Failed to save audit log: {e}", exc_info=True)
            if db:
                db.rollback()
            raise
        finally:
            if db:
                db.close()

    def _determine_action(self, method: str, path: str) -> str:
        """
        Determine action name from HTTP method and path.
        Returns a descriptive action string for audit logs.
        """
        # Check for specific endpoint mappings first
        for endpoint, action in self.ACTION_MAPPINGS.items():
            if endpoint in path:
                return action
        
        # Handle DELETE operations specially
        if method == "DELETE":
            if "/documents/" in path:
                return "document_delete"
            if "/contracts/" in path:
                return "contract_delete"
        
        # Default: method + last path segment
        last_segment = path.rstrip("/").split("/")[-1] or "root"
        return f"{method.lower()}_{last_segment}"

    def _extract_resource_type(self, path: str) -> str:
        """
        Extract resource type from request path.
        Returns the type of resource being accessed.
        """
        # Check each resource mapping
        for resource_type, path_fragments in self.RESOURCE_MAPPINGS.items():
            if any(fragment in path for fragment in path_fragments):
                return resource_type
        
        return "unknown"