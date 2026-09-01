"""The conversion engine.

Ties detection, MarkItDown, OCR and normalization into one call. The decision
this module exists to make is *when to run OCR*, because OCR is expensive and
running it on a normal text PDF is both slow and worse than the real text
layer.

The rule for PDFs::

    PDF
     |
     +-- extract text with MarkItDown
     |
     +-- is there meaningful text? (characters per page)
          |
          +-- yes -> use it
          |
          +-- no  -> the pages are images: run the OCR pipeline

Images always go to OCR, since there is nothing else to extract. Everything
else goes straight to MarkItDown.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.conversion.errors import (
    ConversionCancelledError,
    EmptyResultError,
    OcrUnavailableError,
)
from app.conversion.markitdown_adapter import MarkItDownAdapter
from app.conversion.normalize import (
    contains_raw_html,
    estimate_reading_stats,
    normalize_markdown,
)
from app.conversion.registry import get_registry
from app.conversion.result import ConversionMetadata, ConversionResult
from app.logging_setup import get_logger
from app.ocr.rasterize import page_count
from app.ocr.service import OcrService
from app.security.detection import DetectionResult, detect_format

logger = get_logger(__name__)

STAGE_DETECTING = "detecting"
STAGE_CONVERTING = "converting"
STAGE_OCR = "ocr"
STAGE_FINALIZING = "finalizing"

OCR_AUTO = "auto"
OCR_FORCE = "force"
OCR_OFF = "off"
OCR_MODES = (OCR_AUTO, OCR_FORCE, OCR_OFF)

_PAGE_RANGE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")
MAX_PAGE_RANGE_PAGES = 500


class CancelledSignal(Exception):
    """Raised internally when a cancellation callback reports a stop."""


@dataclass
class ConversionOptions:
    """User-facing conversion settings. Every field has a safe default."""

    ocr_mode: str = OCR_AUTO
    ocr_languages: str | None = None
    page_range: str | None = None

    def normalized_mode(self) -> str:
        mode = (self.ocr_mode or OCR_AUTO).strip().lower()
        return mode if mode in OCR_MODES else OCR_AUTO


@dataclass
class ArchiveMarker:
    """Signals that the input is an archive the job runner must expand."""

    detection: DetectionResult


def parse_page_range(spec: str | None) -> list[int] | None:
    """Parse "1-3,7,10-12" into a sorted page list. None means every page."""
    if not spec or not spec.strip():
        return None

    pages: set[int] = set()
    for part in spec.split(","):
        if not part.strip():
            continue
        match = _PAGE_RANGE.match(part)
        if not match:
            raise ValueError(f"'{part.strip()}' is not a valid page range")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if start < 1 or end < start:
            raise ValueError(f"'{part.strip()}' is not a valid page range")
        if end - start + 1 > MAX_PAGE_RANGE_PAGES:
            raise ValueError("that page range covers too many pages")
        pages.update(range(start, end + 1))

    if not pages:
        return None
    if len(pages) > MAX_PAGE_RANGE_PAGES:
        raise ValueError("that page range covers too many pages")
    return sorted(pages)


class ConversionEngine:
    def __init__(self, settings: Settings, ocr_service: OcrService | None = None):
        self._settings = settings
        self._adapter = MarkItDownAdapter(settings)
        self._ocr = ocr_service or OcrService(settings)

    @property
    def ocr(self) -> OcrService:
        return self._ocr

    @property
    def engine_version(self) -> str:
        return self._adapter.engine_version

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _check_cancelled(should_cancel: Callable[[], bool] | None) -> None:
        if should_cancel is not None and should_cancel():
            raise ConversionCancelledError("cancelled by the client")

    def _has_meaningful_text(self, markdown: str, pages: int) -> bool:
        """Whether an extracted text layer is substantive enough to trust."""
        density = len(markdown.strip()) / max(pages, 1)
        return density >= self._settings.ocr_pdf_text_threshold_chars_per_page

    def _slice_pdf(self, path: Path, pages: list[int], workdir: Path) -> Path:
        """Write a new PDF containing only ``pages`` (1-based)."""
        import pypdfium2 as pdfium

        source = pdfium.PdfDocument(str(path))
        try:
            valid = [p - 1 for p in pages if 1 <= p <= len(source)]
            if not valid:
                raise ValueError("the requested page range is outside this document")
            destination = pdfium.PdfDocument.new()
            destination.import_pages(source, valid)
            target = workdir / "page-range.pdf"
            destination.save(str(target))
            destination.close()
            return target
        finally:
            source.close()

    # --- conversion -------------------------------------------------------

    def convert(
        self,
        path: Path,
        *,
        filename: str,
        options: ConversionOptions | None = None,
        workdir: Path | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> ConversionResult | ArchiveMarker:
        """Convert one file. Archives are returned as a marker for the caller.

        ``on_stage`` reports real progress transitions so the UI can show that
        OCR started because the document needed it - never a simulated bar.
        """
        options = options or ConversionOptions()
        stage = on_stage or (lambda _s: None)
        stage(STAGE_DETECTING)
        started = time.monotonic()
        source_bytes = path.stat().st_size

        detection = detect_format(path, filename)
        extension = detection.detected_extension
        fmt = get_registry().by_extension(extension) or detection.format

        if extension == ".zip":
            return ArchiveMarker(detection=detection)

        self._check_cancelled(should_cancel)

        metadata = ConversionMetadata(
            format=extension.lstrip("."),
            label=fmt.label,
            category=fmt.category,
            source_bytes=source_bytes,
            engine=f"markitdown {self.engine_version}",
        )
        warnings: list[str] = []

        if fmt.category == "images":
            markdown = self._convert_image(
                path, options, metadata, warnings, should_cancel, stage
            )
        elif extension == ".pdf":
            markdown = self._convert_pdf(
                path, options, metadata, warnings, workdir, should_cancel, stage
            )
        else:
            stage(STAGE_CONVERTING)
            raw = self._adapter.convert(
                path,
                extension=extension,
                filename=filename,
                charset=detection.charset,
            )
            metadata.title = raw.title
            markdown = raw.markdown

        self._check_cancelled(should_cancel)
        stage(STAGE_FINALIZING)
        markdown = normalize_markdown(markdown)

        if not markdown.strip():
            raise EmptyResultError("conversion produced no content")

        markdown, truncated = self._apply_output_cap(markdown)
        if truncated:
            warnings.append(
                "This document produced more Markdown than the size limit "
                "allows, so the output was truncated."
            )

        words, characters = estimate_reading_stats(markdown)
        metadata.word_count = words
        metadata.character_count = characters
        metadata.contains_raw_html = contains_raw_html(markdown)
        metadata.duration_ms = int((time.monotonic() - started) * 1000)

        if metadata.contains_raw_html:
            warnings.append(
                "This document contained embedded HTML, which is shown as plain "
                "text in the preview."
            )

        return ConversionResult(
            markdown=markdown, metadata=metadata, warnings=warnings
        )

    def _apply_output_cap(self, markdown: str) -> tuple[str, bool]:
        """Bound the size of a single result.

        Results are held in memory, and a modest spreadsheet can expand into
        millions of words, so the upload limit alone does not bound what one
        conversion costs. Truncation is at a line boundary and is always
        reported to the user rather than applied silently.
        """
        limit = self._settings.max_output_characters
        if len(markdown) <= limit:
            return markdown, False

        clipped = markdown[:limit]
        boundary = clipped.rfind("\n")
        if boundary > limit // 2:
            clipped = clipped[:boundary]
        notice = (
            "\n\n---\n\n"
            "_Output truncated: this document exceeded the size limit._\n"
        )
        logger.info(
            "output truncated",
            extra={"original_characters": len(markdown), "limit": limit},
        )
        return clipped.rstrip() + notice, True

    # --- per-format paths -------------------------------------------------

    def _convert_image(
        self,
        path: Path,
        options: ConversionOptions,
        metadata: ConversionMetadata,
        warnings: list[str],
        should_cancel: Callable[[], bool] | None,
        stage: Callable[[str], None],
    ) -> str:
        mode = options.normalized_mode()
        if mode == OCR_OFF:
            raise OcrUnavailableError(
                "OCR is switched off",
                message="Reading an image needs OCR, which is switched off for "
                "this conversion.",
            )
        if not self._ocr.is_available():
            raise OcrUnavailableError("no OCR provider is available")

        self._check_cancelled(should_cancel)
        stage(STAGE_OCR)
        result = self._ocr.recognize_image(path, languages=options.ocr_languages)

        metadata.ocr_used = True
        metadata.ocr_languages = result.languages
        metadata.ocr_confidence = (
            round(result.confidence, 1) if result.confidence >= 0 else None
        )
        metadata.ocr_pages = result.pages
        metadata.engine = f"{metadata.engine} + ocr:{result.provider}"
        warnings.extend(result.warnings)
        return result.markdown

    def _convert_pdf(
        self,
        path: Path,
        options: ConversionOptions,
        metadata: ConversionMetadata,
        warnings: list[str],
        workdir: Path | None,
        should_cancel: Callable[[], bool] | None,
        stage: Callable[[str], None],
    ) -> str:
        mode = options.normalized_mode()
        selected_pages = parse_page_range(options.page_range)
        target = path

        if selected_pages is not None:
            if workdir is None:
                raise ValueError("a working directory is required for page ranges")
            target = self._slice_pdf(path, selected_pages, workdir)
            warnings.append(
                f"Only pages {options.page_range} were converted, as requested."
            )

        pages = page_count(target)
        metadata.pages = pages or None

        text_markdown = ""
        if mode != OCR_FORCE:
            stage(STAGE_CONVERTING)
            raw = self._adapter.convert(
                target, extension=".pdf", filename=path.name
            )
            metadata.title = raw.title
            text_markdown = raw.markdown

        self._check_cancelled(should_cancel)

        if mode == OCR_OFF:
            return text_markdown

        needs_ocr = mode == OCR_FORCE or not self._has_meaningful_text(
            text_markdown, pages or 1
        )
        if not needs_ocr:
            return text_markdown

        if not self._ocr.is_available():
            if text_markdown.strip():
                warnings.append(
                    "This PDF looks scanned, but OCR isn't available, so only "
                    "its embedded text was extracted."
                )
                return text_markdown
            raise OcrUnavailableError("no OCR provider is available")

        stage(STAGE_OCR)
        logger.info(
            "routing PDF to OCR",
            extra={
                "pages": pages,
                "reason": "forced" if mode == OCR_FORCE else "no_text_layer",
            },
        )

        result = self._ocr.recognize_pdf(
            target,
            languages=options.ocr_languages,
            should_cancel=should_cancel,
        )

        metadata.ocr_used = True
        metadata.ocr_languages = result.languages
        metadata.ocr_confidence = (
            round(result.confidence, 1) if result.confidence >= 0 else None
        )
        metadata.ocr_pages = result.pages
        metadata.engine = f"{metadata.engine} + ocr:{result.provider}"
        warnings.extend(result.warnings)

        # If OCR somehow found less than the text layer, keep the better one.
        if len(result.markdown.strip()) < len(text_markdown.strip()):
            metadata.ocr_used = False
            warnings.append(
                "OCR found less text than the document's own text layer, so the "
                "text layer was used."
            )
            return text_markdown

        return result.markdown
