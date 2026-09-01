"""API response models.

These types define the entire public surface. Note what they deliberately omit:
no filesystem paths, no workspace directories, no session-internal ids beyond
the opaque ones the client already holds, and no stack traces.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error identifier")
    message: str = Field(description="Sentence safe to show a user")
    detail: str | None = Field(
        default=None,
        description="Technical explanation, shown behind 'Show details'",
    )


class ErrorResponse(BaseModel):
    error: ErrorBody


class FormatModel(BaseModel):
    extension: str
    label: str
    category: str
    icon: str
    mime_types: list[str]
    ocr_capable: bool


class CategoryModel(BaseModel):
    id: str
    label: str
    description: str


class FormatsResponse(BaseModel):
    categories: list[CategoryModel]
    formats: list[FormatModel]
    limits: dict[str, int]


class FileResult(BaseModel):
    id: str
    filename: str
    output_filename: str
    size: int
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    stage: str | None = None
    source_archive: str | None = None
    metadata: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: ErrorBody | None = None


class JobResponse(BaseModel):
    id: str
    status: str
    created_at: str
    file_count: int
    completed_count: int
    files: list[FileResult]


class JobCreatedResponse(JobResponse):
    session_id: str
    session_token: str
    expires_at: str


class MarkdownResponse(BaseModel):
    id: str
    filename: str
    output_filename: str
    format: str
    status: str
    markdown: str
    metadata: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


class EditedFile(BaseModel):
    """A result the user edited in the browser before downloading."""

    id: str
    markdown: str = Field(max_length=20_000_000)


class DownloadAllRequest(BaseModel):
    files: list[EditedFile] = Field(default_factory=list, max_length=200)


class OcrStatus(BaseModel):
    enabled: bool
    available: bool
    active_provider: str | None
    languages: list[str]
    default_languages: str


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    engine: str
    ocr: OcrStatus
    workspace_writable: bool
    active_sessions: int
