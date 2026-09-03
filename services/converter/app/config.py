"""Application configuration.

All tunables are environment-driven so the same image can be deployed with
different resource envelopes. Defaults are chosen to be safe for a public,
anonymous converter rather than maximally permissive.
"""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment -----------------------------------------------------
    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # Comma-separated list of origins allowed to call the API directly.
    # In production the browser talks to Next.js, which proxies to this
    # service over the internal network, so this stays tight.
    cors_origins: str = "http://localhost:3000"
    # Managed hosts give every preview deployment a generated domain, which no
    # fixed list can cover. A regex is the only workable way to allow them,
    # so anchor it tightly - a loose pattern allows the whole internet.
    # Example: ^https://markpilot-[a-z0-9-]+\.vercel\.app$
    cors_origin_regex: str | None = None

    # --- Upload limits ---------------------------------------------------
    max_file_size_mb: int = 50
    max_total_upload_mb: int = 200
    max_files_per_job: int = 20

    # --- Archive limits --------------------------------------------------
    max_archive_size_mb: int = 100
    max_archive_files: int = 100
    # Guards against zip bombs: total uncompressed bytes and per-entry ratio.
    max_archive_uncompressed_mb: int = 400
    max_archive_compression_ratio: int = 200
    max_archive_depth: int = 1

    # --- Conversion ------------------------------------------------------
    # MarkItDown discovers third-party plugins via the "markitdown.plugin"
    # entry-point group. That is arbitrary code executing on untrusted input,
    # so it stays opt-in and off by default.
    markitdown_plugins_enabled: bool = False
    max_conversion_time_seconds: int = 300
    # Cap on generated Markdown. A small spreadsheet can expand into millions
    # of words, and results are held in memory - so the input size limit alone
    # does not bound what a single conversion costs.
    max_output_characters: int = 4_000_000
    max_concurrent_conversions: int = 4

    # --- Sessions --------------------------------------------------------
    session_ttl_minutes: int = 30
    cleanup_interval_seconds: int = 120
    workspace_root: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "markpilot"
    )

    # --- OCR -------------------------------------------------------------
    ocr_enabled: bool = True
    ocr_languages: str = "eng+ben"
    tesseract_cmd: str | None = None
    tessdata_prefix: str | None = None
    ocr_dpi: int = 300
    ocr_max_pages: int = 100
    # A PDF page yielding fewer extractable characters than this is treated
    # as image-only and routed to OCR.
    ocr_pdf_text_threshold_chars_per_page: int = 100
    # Mean word confidence (0-100) below which we surface a quality warning.
    ocr_low_confidence_threshold: float = 70.0

    # --- Optional vision provider (off unless fully configured) ----------
    vision_ocr_enabled: bool = False
    vision_api_base_url: str = "https://api.openai.com/v1"
    vision_api_key: str | None = None
    vision_model: str | None = None

    # --- Rate limiting ---------------------------------------------------
    rate_limit_enabled: bool = True
    # Only honour X-Forwarded-For when a trusted reverse proxy sets it.
    # Enabled blindly, any client could spoof the header and evade the limiter.
    trust_proxy_headers: bool = False
    rate_limit_jobs_per_hour: int = 40
    rate_limit_uploads_mb_per_hour: int = 500

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_total_upload_bytes(self) -> int:
        return self.max_total_upload_mb * 1024 * 1024

    @property
    def max_archive_size_bytes(self) -> int:
        return self.max_archive_size_mb * 1024 * 1024

    @property
    def max_archive_uncompressed_bytes(self) -> int:
        return self.max_archive_uncompressed_mb * 1024 * 1024

    @property
    def vision_configured(self) -> bool:
        return bool(
            self.vision_ocr_enabled and self.vision_api_key and self.vision_model
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
