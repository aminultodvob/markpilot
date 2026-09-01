"""Shared application services and request helpers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, Request

from app.cleanup.worker import CleanupWorker
from app.config import Settings
from app.conversion.engine import ConversionEngine
from app.conversion.errors import NotAuthorizedError
from app.jobs.runner import JobRunner
from app.security.ratelimit import RateLimiter
from app.sessions.manager import Session, SessionManager

SESSION_ID_HEADER = "X-Session-Id"
SESSION_TOKEN_HEADER = "X-Session-Token"


@dataclass
class Services:
    """Everything constructed once at startup and shared by requests."""

    settings: Settings
    engine: ConversionEngine
    sessions: SessionManager
    runner: JobRunner
    rate_limiter: RateLimiter
    cleanup: CleanupWorker

    def shutdown(self) -> None:
        self.cleanup.stop()
        self.runner.shutdown()
        # Uploaded files must not outlive the process that accepted them.
        self.sessions.shutdown()


def get_services(request: Request) -> Services:
    return request.app.state.services


def client_address(request: Request) -> str:
    """Best-effort client address for rate limiting.

    ``X-Forwarded-For`` is only honoured when the deployment declares a trusted
    proxy, because otherwise any client could spoof it and bypass the limiter.
    """
    services = get_services(request)
    if services.settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_session(
    request: Request,
    x_session_id: str | None = Header(default=None, alias=SESSION_ID_HEADER),
    x_session_token: str | None = Header(default=None, alias=SESSION_TOKEN_HEADER),
) -> Session:
    """Resolve and authorize the caller's session, or fail closed."""
    if not x_session_id:
        raise NotAuthorizedError("missing session id")
    services = get_services(request)
    return services.sessions.authorize(x_session_id, x_session_token)
