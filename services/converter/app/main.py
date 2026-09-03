"""FastAPI application for the MarkPilot converter service.

This service is meant to sit on an internal network behind the web app, not on
the public internet. It stores nothing durably: uploads live in a per-session
temporary directory, results live in memory, and both are removed on expiry,
on request, or at shutdown.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import Services
from app.api.routes import router
from app.api.schemas import ErrorBody, ErrorResponse
from app.cleanup.worker import CleanupWorker
from app.config import get_settings
from app.conversion.engine import ConversionEngine
from app.conversion.errors import ConversionError
from app.jobs.runner import JobRunner
from app.logging_setup import configure_logging, get_logger
from app.security.ratelimit import RateLimiter
from app.sessions.manager import SessionManager

logger = get_logger(__name__)

DESCRIPTION = (
    "Converts documents to Markdown using Microsoft MarkItDown, with an OCR "
    "pipeline for scanned pages and images. Files are processed temporarily "
    "and are not stored permanently."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = ConversionEngine(settings)
    sessions = SessionManager(settings)
    rate_limiter = RateLimiter(
        enabled=settings.rate_limit_enabled,
        jobs_per_hour=settings.rate_limit_jobs_per_hour,
        upload_mb_per_hour=settings.rate_limit_uploads_mb_per_hour,
    )
    runner = JobRunner(settings, engine, sessions)
    cleanup = CleanupWorker(sessions, settings, rate_limiter)
    cleanup.start()

    app.state.services = Services(
        settings=settings,
        engine=engine,
        sessions=sessions,
        runner=runner,
        rate_limiter=rate_limiter,
        cleanup=cleanup,
    )

    ocr = engine.ocr
    cors_configured = bool(settings.cors_origin_list or settings.cors_origin_regex)
    logger.info(
        "converter service started",
        extra={
            "app_env": settings.app_env,
            "engine": engine.engine_version,
            "ocr_available": ocr.is_available(),
            "ocr_provider": ocr.provider.name if ocr.provider else None,
            "ocr_languages": ocr.available_languages(),
            "cors_origins": settings.cors_origin_list,
            "cors_origin_regex": settings.cors_origin_regex,
        },
    )
    # A public converter with no allowed origins accepts no browser at all:
    # every request is refused at the CORS preflight. Surface it loudly, since
    # the browser-side symptom ("couldn't reach the converter") points nowhere.
    if settings.app_env == "production" and not cors_configured:
        logger.warning(
            "no CORS origins configured: browsers will be blocked. Set "
            "CORS_ORIGINS or CORS_ORIGIN_REGEX to your web app's origin.",
        )

    try:
        yield
    finally:
        app.state.services.shutdown()
        logger.info("converter service stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MarkPilot Converter",
        description=DESCRIPTION,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex,
        # No cookies are used; the session token is an explicit header.
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Session-Id", "X-Session-Token"],
        max_age=600,
    )

    @app.exception_handler(ConversionError)
    async def handle_conversion_error(
        request: Request, exc: ConversionError
    ) -> JSONResponse:
        """Turn any expected failure into a stable, non-leaking error body."""
        body = ErrorResponse(
            error=ErrorBody(code=exc.code, message=exc.message, detail=exc.detail)
        )
        headers = {}
        if exc.code == "rate_limited":
            headers["Retry-After"] = "60"
        return JSONResponse(
            status_code=exc.http_status, content=body.model_dump(), headers=headers
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it.
        logger.error(
            "unhandled request error",
            extra={"path": request.url.path, "error_type": type(exc).__name__},
            exc_info=True,
        )
        body = ErrorResponse(
            error=ErrorBody(
                code="internal_error",
                message="Something went wrong on our side. Please try again.",
            )
        )
        return JSONResponse(status_code=500, content=body.model_dump())

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # This service returns JSON and file downloads only; nothing should
        # ever be rendered from its origin.
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        return response

    app.include_router(router)
    return app


app = create_app()
