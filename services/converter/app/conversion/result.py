"""The shape of a conversion result.

Everything the API returns about a converted file is described here. Note what
is absent: no filesystem paths, no session directories, no internal ids beyond
the opaque ones the client already holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversionMetadata:
    """Facts about how a file was converted, safe to show a user."""

    format: str
    label: str
    category: str
    duration_ms: int = 0
    source_bytes: int = 0
    word_count: int = 0
    character_count: int = 0
    pages: int | None = None
    sheets: int | None = None
    slides: int | None = None
    title: str | None = None
    ocr_used: bool = False
    ocr_languages: str | None = None
    ocr_confidence: float | None = None
    ocr_pages: int | None = None
    contains_raw_html: bool = False
    engine: str = "markitdown"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "format": self.format,
            "label": self.label,
            "category": self.category,
            "duration_ms": self.duration_ms,
            "source_bytes": self.source_bytes,
            "word_count": self.word_count,
            "character_count": self.character_count,
            "ocr_used": self.ocr_used,
            "contains_raw_html": self.contains_raw_html,
            "engine": self.engine,
        }
        optional = {
            "pages": self.pages,
            "sheets": self.sheets,
            "slides": self.slides,
            "title": self.title,
            "ocr_languages": self.ocr_languages,
            "ocr_confidence": self.ocr_confidence,
            "ocr_pages": self.ocr_pages,
        }
        data.update({k: v for k, v in optional.items() if v is not None})
        return data


@dataclass
class ConversionResult:
    markdown: str
    metadata: ConversionMetadata
    warnings: list[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


@dataclass
class RawConversion:
    """What the underlying engine produced, before our post-processing."""

    markdown: str
    title: str | None = None
