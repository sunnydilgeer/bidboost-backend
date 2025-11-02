from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.database import SessionLocal
from app.models import AuditLog
import time
import logging

logger = logging.getLogger(__name__)

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        print(f"🔍 Audit middleware triggered: {request.method} {request.url.path}")
        start_time = time.time()
        
        # Get user info from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
        firm_id = getattr(request.state, "firm_id", None)
        
        print(f"   User ID: {user_id}, Firm ID: {firm_id}")
        
        # Skip audit logging for health/docs endpoints
        skip_paths = ["/health", "/ready", "/docs", "/redoc", "/openapi.json", "/favicon.ico"]
        if any(request.url.path.startswith(path) for path in skip_paths):
            return await call_next(request)
        
        # Process request
        response = await call_next(request)
        
        # Log ALL requests (not just authenticated ones)
        latency_ms = int((time.time() - start_time) * 1000)
        action = self._determine_action(request.method, request.url.path)
        
        print(f"   Logging action: {action}, Status: {response.status_code}")
        
        # Log to database
        try:
            db = SessionLocal()
            audit_entry = AuditLog(
                user_id=user_id if user_id else None,  # Changed: allow NULL
                firm_id=firm_id if firm_id else None,  # Changed: allow NULL
                action=action,
                resource_type=self._extract_resource_type(request.url.path),
                details={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "user_email": user_id  # user_id is actually the email
                },
                ip_address=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("user-agent", "")
            )
            db.add(audit_entry)
            db.commit()
            print(f"   ✅ Audit log saved successfully")
        except Exception as e:
            logger.error(f"❌ Audit logging failed: {e}")
            print(f"   ❌ Audit logging failed: {e}")
        finally:
            db.close()
        
        return response
    
    def _determine_action(self, method: str, path: str) -> str:
        """Map HTTP method + path to action name"""
        if "/auth/login" in path:
            return "user_login"
        elif "/auth/register" in path:
            return "user_register"
        elif "/documents/upload" in path:
            return "document_upload"
        elif "/documents" in path and method == "DELETE":
            return "document_delete"
        elif "/query" in path:
            return "query_executed"
        else:
            return f"{method.lower()}_{path.split('/')[-1]}"
    
    def _extract_resource_type(self, path: str) -> str:
        """Extract resource type from path"""
        if "/auth" in path:
            return "auth"
        elif "/documents" in path:
            return "document"
        elif "/query" in path:
            return "query"
        elif "/conversations" in path:
            return "conversation"
        return "unknown"