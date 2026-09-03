"""HTTP API.

Design notes:

* One job carries many files. Small single-file conversions still finish in one
  poll, so there was no reason to build two separate code paths.
* Every result is addressed by an opaque id and reached only through the
  session that produced it, verified by a bearer token. There is no endpoint
  anywhere that accepts a path.
* Uploads are streamed to disk with the size cap enforced *as bytes arrive*,
  never by trusting a Content-Length header.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import Services, client_address, get_services, require_session
from app.api.schemas import (
    CategoryModel,
    CorsStatus,
    DownloadAllRequest,
    ErrorBody,
    FileResult,
    FormatModel,
    FormatsResponse,
    HealthResponse,
    JobCreatedResponse,
    JobResponse,
    MarkdownResponse,
    OcrStatus,
    ReadyResponse,
)
from app.conversion.engine import ConversionOptions
from app.conversion.errors import (
    ConversionError,
    FileTooLargeError,
    RateLimitedError,
    SessionNotFoundError,
    TooManyFilesError,
)
from app.conversion.registry import get_registry
from app.logging_setup import get_logger
from app.security.filenames import (
    dedupe_name,
    header_safe,
    markdown_name,
    sanitize_filename,
)
from app.security.ratelimit import client_key
from app.sessions.manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    Job,
    JobFile,
    Session,
)

logger = get_logger(__name__)
router = APIRouter()

UPLOAD_CHUNK = 1024 * 1024
ZIP_ARCHIVE_NAME = "markpilot-results.zip"


# --- serialization ----------------------------------------------------------


def _file_result(job_file: JobFile) -> FileResult:
    error = None
    if job_file.status == STATUS_FAILED and job_file.error_code:
        error = ErrorBody(
            code=job_file.error_code,
            message=job_file.error_message or "We couldn't convert this file.",
            detail=job_file.error_detail,
        )
    return FileResult(
        id=job_file.id,
        filename=job_file.filename,
        output_filename=markdown_name(job_file.filename),
        size=job_file.size,
        status=job_file.status,
        stage=job_file.stage,
        source_archive=job_file.source_archive,
        metadata=job_file.result.metadata.to_dict() if job_file.result else None,
        warnings=job_file.result.warnings if job_file.result else [],
        error=error,
    )


def _job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at.isoformat(),
        file_count=len(job.files),
        completed_count=job.completed_count,
        files=[_file_result(f) for f in job.files],
    )


def _options_from_form(
    ocr_mode: str, ocr_languages: str | None, page_range: str | None
) -> ConversionOptions:
    return ConversionOptions(
        ocr_mode=ocr_mode,
        ocr_languages=(ocr_languages or "").strip() or None,
        page_range=(page_range or "").strip() or None,
    )


def _content_disposition(filename: str) -> str:
    """RFC 5987 disposition so non-ASCII names (e.g. Bengali) survive."""
    return (
        f"attachment; filename=\"{header_safe(filename)}\"; "
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


# --- health -----------------------------------------------------------------


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health(services: Services = Depends(get_services)) -> HealthResponse:
    """Liveness only. Deliberately does no work and touches no documents."""
    return HealthResponse(status="ok", version=services.engine.engine_version)


@router.get("/ready", response_model=ReadyResponse, tags=["health"])
def ready(services: Services = Depends(get_services)) -> ReadyResponse:
    """Readiness: verifies the workspace is writable and reports OCR status."""
    workspace_writable = False
    try:
        probe = services.sessions.root / ".readiness"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        workspace_writable = True
    except OSError:
        logger.warning("workspace is not writable")

    ocr = services.engine.ocr
    settings = services.settings
    status = "ok" if workspace_writable else "degraded"
    return ReadyResponse(
        status=status,
        engine=f"markitdown {services.engine.engine_version}",
        ocr=OcrStatus(
            enabled=settings.ocr_enabled,
            available=ocr.is_available(),
            active_provider=ocr.provider.name if ocr.provider else None,
            languages=ocr.available_languages(),
            default_languages=settings.ocr_languages,
        ),
        cors=CorsStatus(
            allowed_origins=settings.cors_origin_list,
            origin_regex=settings.cors_origin_regex,
            configured=bool(settings.cors_origin_list or settings.cors_origin_regex),
        ),
        workspace_writable=workspace_writable,
        active_sessions=services.sessions.active_session_count(),
    )


# --- formats ----------------------------------------------------------------


@router.get("/api/v1/formats", response_model=FormatsResponse, tags=["formats"])
def formats(services: Services = Depends(get_services)) -> FormatsResponse:
    """The format registry, so the UI never keeps its own copy of the list."""
    registry = get_registry()
    settings = services.settings
    return FormatsResponse(
        categories=[
            CategoryModel(id=c.id, label=c.label, description=c.description)
            for c in registry.categories
        ],
        formats=[
            FormatModel(
                extension=f.extension,
                label=f.label,
                category=f.category,
                icon=f.icon,
                mime_types=list(f.mime_types),
                ocr_capable=f.ocr_capable,
            )
            for f in registry.formats
        ],
        limits={
            "max_file_size_mb": settings.max_file_size_mb,
            "max_total_upload_mb": settings.max_total_upload_mb,
            "max_files_per_job": settings.max_files_per_job,
            "session_ttl_minutes": settings.session_ttl_minutes,
        },
    )


# --- jobs -------------------------------------------------------------------


async def _store_upload(upload: UploadFile, destination: Path, limit: int) -> int:
    """Stream an upload to disk, aborting the moment it exceeds ``limit``."""
    written = 0
    with destination.open("wb") as sink:
        while chunk := await upload.read(UPLOAD_CHUNK):
            written += len(chunk)
            if written > limit:
                sink.close()
                destination.unlink(missing_ok=True)
                raise FileTooLargeError(
                    f"{upload.filename} exceeds the per-file limit"
                )
            sink.write(chunk)
    return written


@router.post(
    "/api/v1/jobs",
    response_model=JobCreatedResponse,
    status_code=201,
    tags=["jobs"],
)
async def create_job(
    request: Request,
    files: list[UploadFile] = File(...),
    ocr_mode: str = Form("auto"),
    ocr_languages: str | None = Form(None),
    page_range: str | None = Form(None),
    services: Services = Depends(get_services),
) -> JSONResponse:
    """Upload files and start converting them."""
    settings = services.settings

    if not files:
        raise ConversionError("no files uploaded", message="Please choose a file.")
    if len(files) > settings.max_files_per_job:
        raise TooManyFilesError(
            f"{len(files)} files exceeds the limit of {settings.max_files_per_job}"
        )

    decision = services.rate_limiter.check(
        client_key(client_address(request)),
        # Reserve against the declared size; the real total is capped below.
        min(
            int(request.headers.get("content-length") or 0),
            settings.max_total_upload_bytes,
        ),
    )
    if not decision.allowed:
        raise RateLimitedError(
            decision.reason, message=decision.reason or RateLimitedError.message
        )

    session = services.sessions.create()
    job = services.sessions.create_job(session)

    total = 0
    taken: set[str] = set()
    try:
        for upload in files:
            safe_name = dedupe_name(sanitize_filename(upload.filename), taken)
            taken.add(safe_name)

            file_id = services.sessions.new_file_id()
            # Storage name is generated: the uploaded name never forms a path.
            stored = session.uploads / file_id

            size = await _store_upload(upload, stored, settings.max_file_size_bytes)
            total += size
            if total > settings.max_total_upload_bytes:
                stored.unlink(missing_ok=True)
                raise FileTooLargeError(
                    "the upload exceeds the total size limit",
                    message="Those files are larger than the total upload limit.",
                )

            job.files.append(
                JobFile(
                    id=file_id, filename=safe_name, size=size, stored_path=stored
                )
            )
    except Exception:
        services.sessions.delete(session.id)
        raise

    options = _options_from_form(ocr_mode, ocr_languages, page_range)
    services.runner.submit(session, job, options)

    logger.info(
        "job created",
        extra={"file_count": len(job.files), "total_bytes": total},
    )

    payload = JobCreatedResponse(
        **_job_response(job).model_dump(),
        session_id=session.id,
        session_token=session.token,
        expires_at=session.expires_at.isoformat(),
    )
    return JSONResponse(status_code=201, content=payload.model_dump())


@router.get("/api/v1/jobs/{job_id}", response_model=JobResponse, tags=["jobs"])
def get_job(
    job_id: str,
    session: Session = Depends(require_session),
    services: Services = Depends(get_services),
) -> JobResponse:
    """Poll a job's progress."""
    return _job_response(services.sessions.get_job(session, job_id))


@router.get(
    "/api/v1/jobs/{job_id}/files/{file_id}",
    response_model=MarkdownResponse,
    tags=["jobs"],
)
def get_file_markdown(
    job_id: str,
    file_id: str,
    session: Session = Depends(require_session),
    services: Services = Depends(get_services),
) -> MarkdownResponse:
    """Fetch one file's Markdown and metadata."""
    job = services.sessions.get_job(session, job_id)
    job_file = job.file(file_id)
    if job_file is None:
        raise SessionNotFoundError("file not found in this job")
    if job_file.status != STATUS_COMPLETED or job_file.result is None:
        raise ConversionError(
            "file has not completed",
            message="This file hasn't finished converting yet.",
        )

    return MarkdownResponse(
        id=job_file.id,
        filename=job_file.filename,
        output_filename=markdown_name(job_file.filename),
        format=job_file.result.metadata.format,
        status=job_file.status,
        markdown=job_file.markdown or "",
        metadata=job_file.result.metadata.to_dict(),
        warnings=job_file.result.warnings,
    )


@router.post("/api/v1/jobs/{job_id}/cancel", response_model=JobResponse, tags=["jobs"])
def cancel_job(
    job_id: str,
    session: Session = Depends(require_session),
    services: Services = Depends(get_services),
) -> JobResponse:
    """Stop a running job. Work in flight halts at its next checkpoint."""
    job = services.sessions.get_job(session, job_id)
    affected = services.runner.cancel(job)
    logger.info("job cancelled", extra={"affected_files": affected})
    return _job_response(job)


@router.post(
    "/api/v1/jobs/{job_id}/files/{file_id}/retry",
    response_model=JobResponse,
    tags=["jobs"],
)
def retry_file(
    job_id: str,
    file_id: str,
    ocr_mode: str = Form("auto"),
    ocr_languages: str | None = Form(None),
    page_range: str | None = Form(None),
    session: Session = Depends(require_session),
    services: Services = Depends(get_services),
) -> JobResponse:
    """Re-run one file from the copy still held in the session workspace."""
    job = services.sessions.get_job(session, job_id)
    job_file = job.file(file_id)
    if job_file is None:
        raise SessionNotFoundError("file not found in this job")

    options = _options_from_form(ocr_mode, ocr_languages, page_range)
    if not services.runner.retry(session, job, job_file, options):
        raise ConversionError(
            "original upload is no longer available",
            message="This file is no longer in the session, so please upload it "
            "again.",
        )
    return _job_response(job)


# --- downloads --------------------------------------------------------------


@router.get("/api/v1/jobs/{job_id}/files/{file_id}/download", tags=["downloads"])
def download_file(
    job_id: str,
    file_id: str,
    session: Session = Depends(require_session),
    services: Services = Depends(get_services),
) -> Response:
    """Download one result as a .md file."""
    job = services.sessions.get_job(session, job_id)
    job_file = job.file(file_id)
    if job_file is None or job_file.markdown is None:
        raise SessionNotFoundError("result not found in this session")

    filename = markdown_name(job_file.filename)
    return Response(
        content=job_file.markdown.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": _content_disposition(filename),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/api/v1/jobs/{job_id}/download", tags=["downloads"])
def download_all(
    job_id: str,
    payload: DownloadAllRequest,
    session: Session = Depends(require_session),
    services: Services = Depends(get_services),
) -> StreamingResponse:
    """Download every result as a ZIP, honouring edits made in the browser.

    The archive is built in memory and streamed; nothing is written to a public
    directory and no durable download URL is created.
    """
    job = services.sessions.get_job(session, job_id)
    edited = {item.id: item.markdown for item in payload.files}

    completed = [
        f for f in job.files if f.status == STATUS_COMPLETED and f.markdown is not None
    ]
    if not completed:
        raise ConversionError(
            "no completed results",
            message="There aren't any converted files to download yet.",
        )

    buffer = io.BytesIO()
    taken: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for job_file in completed:
            name = dedupe_name(markdown_name(job_file.filename), taken)
            taken.add(name)
            content = edited.get(job_file.id, job_file.markdown or "")
            archive.writestr(name, content.encode("utf-8"))
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": _content_disposition(ZIP_ARCHIVE_NAME),
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- sessions ---------------------------------------------------------------


@router.delete("/api/v1/sessions/{session_id}", status_code=204, tags=["sessions"])
def clear_session(
    session_id: str,
    session: Session = Depends(require_session),
    services: Services = Depends(get_services),
) -> Response:
    """Delete a session and every temporary file it owns, immediately."""
    if session_id != session.id:
        raise SessionNotFoundError("session mismatch")
    for job in session.jobs.values():
        services.runner.cancel(job)
    services.sessions.delete(session.id)
    return Response(status_code=204)
