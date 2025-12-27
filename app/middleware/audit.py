from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.database import SessionLocal
from app.models import AuditLog
import time
import logging

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # ✅ IMPORTANT: Skip Stripe webhooks entirely.
        # Stripe signature verification requires the raw body bytes to be untouched.
        if path.startswith("/api/api/billing/webhook") or path.startswith("/api/billing/webhook"):
            return await call_next(request)

        print(f"🔍 Audit middleware triggered: {method} {path}")
        start_time = time.time()

        # Get user info from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
        firm_id = getattr(request.state, "firm_id", None)

        print(f"   User ID: {user_id}, Firm ID: {firm_id}")

        # Skip audit logging for health/docs endpoints
        skip_paths = ["/health", "/ready", "/docs", "/redoc", "/openapi.json", "/favicon.ico"]
        if any(path.startswith(p) for p in skip_paths):
            return await call_next(request)

        # Process request
        response = await call_next(request)

        latency_ms = int((time.time() - start_time) * 1000)
        action = self._determine_action(method, path)

        print(f"   Logging action: {action}, Status: {response.status_code}")

        db = None
        try:
            db = SessionLocal()
            audit_entry = AuditLog(
                user_id=user_id if user_id else None,
                firm_id=firm_id if firm_id else None,
                action=action,
                resource_type=self._extract_resource_type(path),
                details={
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "user_email": user_id,  # user_id is actually the email
                },
                ip_address=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("user-agent", ""),
            )
            db.add(audit_entry)
            db.commit()
            print("   ✅ Audit log saved successfully")
        except Exception as e:
            logger.exception(f"❌ Audit logging failed: {e}")
            print(f"   ❌ Audit logging failed: {e}")
            if db:
                db.rollback()
        finally:
            if db:
                db.close()

        return response

    def _determine_action(self, method: str, path: str) -> str:
        """Map HTTP method + path to action name"""
        if "/auth/login" in path:
            return "user_login"
        if "/auth/register" in path:
            return "user_register"
        if "/documents/upload" in path:
            return "document_upload"
        if "/documents" in path and method == "DELETE":
            return "document_delete"
        if "/query" in path:
            return "query_executed"

        # Default: method + last segment
        last = path.rstrip("/").split("/")[-1] or "root"
        return f"{method.lower()}_{last}"

    def _extract_resource_type(self, path: str) -> str:
        """Extract resource type from path"""
        if "/auth" in path:
            return "auth"
        if "/documents" in path:
            return "document"
        if "/query" in path:
            return "query"
        if "/conversations" in path:
            return "conversation"
        if "/billing" in path:
            return "billing"
        return "unknown"