# ruff: noqa: E501
"""Every file handed out as a download (Excel, PDF, Word, a zip) is in the audit log: who, which
address, when. The audit log viewer shows them under "Exports"."""

import jwt
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app import audit
from app.auth.security import decode_access
from app.db import SessionLocal

SKIP = ("/api/auth/", "/api/health")


def _record(user_id, path: str, query: str, filename: str, ip: str | None) -> None:
    with SessionLocal() as db:
        audit.record(db, "export", "download", None, user_id=user_id, after={"path": path, "query": query[:300], "file": filename[:200]}, ip=ip)
        db.commit()


class ExportAudit(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        cd = response.headers.get("content-disposition") or ""
        if response.status_code == 200 and "attachment" in cd and not request.url.path.startswith(SKIP):
            user_id = None
            auth = request.headers.get("authorization") or ""
            if auth.lower().startswith("bearer "):
                try:
                    user_id = decode_access(auth[7:])[0]
                except jwt.InvalidTokenError:
                    user_id = None
            name = cd.split("filename=", 1)[1].strip('"') if "filename=" in cd else ""
            ip = audit.client_ip(request)
            await run_in_threadpool(_record, user_id, request.url.path, request.url.query, name, ip)
        return response
