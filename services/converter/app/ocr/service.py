"""OCR orchestration.

Owns provider selection, language resolution, and the page loop. Callers ask
for "OCR this image" or "OCR this PDF" and get Markdown plus an honest quality
signal; they never touch a provider directly.

One detail worth calling out: when a provider returns positioned words, every
page is recognised first and the document's body-text size is computed across
*all* of them before any page is laid out. Reconstructing page-by-page makes
heading levels drift, because a page that happens to contain only large text
would treat that size as its body.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.config import Settings
from app.conversion.errors import CorruptFileError, OcrUnavailableError
from app.logging_setup import get_logger
from app.ocr.base import OcrProvider
from app.ocr.layout import body_text_height, build_lines, reconstruct
from app.ocr.preprocess import preprocess
from app.ocr.rasterize import render_pages
from app.ocr.tesseract import TesseractOcrProvider
from app.ocr.types import OcrDocumentResult, OcrWord
from app.ocr.vision import VisionOcrProvider

logger = get_logger(__name__)

AUTO = "auto"
# Mean word confidence below which we re-check against the unprocessed page.
WEAK_CONFIDENCE = 62.0


class OcrService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tesseract = TesseractOcrProvider(settings)
        self._vision = VisionOcrProvider(settings)

    # --- provider selection ----------------------------------------------

    @property
    def provider(self) -> OcrProvider | None:
        """The best provider currently usable, or None if OCR is off."""
        if not self._settings.ocr_enabled:
            return None
        if self._tesseract.is_available():
            return self._tesseract
        if self._vision.is_available():
            return self._vision
        return None

    def is_available(self) -> bool:
        return self.provider is not None

    def describe(self) -> dict[str, object]:
        return {
            "enabled": self._settings.ocr_enabled,
            "active_provider": self.provider.name if self.provider else None,
            "providers": [self._tesseract.describe(), self._vision.describe()],
            "default_languages": self._settings.ocr_languages,
        }

    def resolve_languages(self, requested: str | None) -> tuple[str, list[str]]:
        """Turn a UI language choice into a provider-usable language string."""
        wanted = (requested or AUTO).strip().lower()
        if wanted in ("", AUTO):
            wanted = self._settings.ocr_languages

        provider = self.provider
        if isinstance(provider, TesseractOcrProvider):
            return provider.resolve_languages(wanted)
        return wanted, []

    def available_languages(self) -> list[str]:
        provider = self.provider
        return provider.supported_languages() if provider else []

    # --- recognition ------------------------------------------------------

    def _require_provider(self) -> OcrProvider:
        provider = self.provider
        if provider is None:
            raise OcrUnavailableError("no OCR provider is available")
        return provider

    @staticmethod
    def _recognition_score(words: list[OcrWord]) -> float:
        """Total recognised confidence: more words, read more certainly."""
        return sum(w.confidence for w in words)

    def _prepare_and_extract(
        self, provider: OcrProvider, image: Image.Image, languages: str
    ) -> tuple[Image.Image, list[OcrWord]]:
        """Recognise a page, falling back to the untouched image if needed.

        Preprocessing is measured and conditional, but no heuristic is perfect:
        on a very faint scan a median filter can erase the thin strokes it was
        meant to clean up. Rather than trust the heuristic absolutely, we check
        the outcome, and if the processed page read worse than the plain one we
        keep the plain one. The second pass only runs when the first went
        badly, so the common case still costs a single recognition.
        """
        prepared, report = preprocess(image)
        prepared, _rotation = provider.orient(prepared)
        words = provider.extract_words(prepared, languages=languages)

        if not report.steps:
            return prepared, words

        mean_confidence = (
            sum(w.confidence for w in words) / len(words) if words else 0.0
        )
        if words and mean_confidence >= WEAK_CONFIDENCE:
            return prepared, words

        baseline, _ = preprocess(image, enabled=False)
        baseline, _rotation = provider.orient(baseline)
        baseline_words = provider.extract_words(baseline, languages=languages)

        if self._recognition_score(baseline_words) > self._recognition_score(words):
            logger.info(
                "kept the unprocessed page: preprocessing read worse",
                extra={"steps": report.steps},
            )
            return baseline, baseline_words
        return prepared, words

    def _finish(
        self,
        *,
        markdown: str,
        confidences: list[tuple[float, int]],
        word_count: int,
        pages: int,
        provider: OcrProvider,
        languages: str,
        warnings: list[str],
    ) -> OcrDocumentResult:
        # Weight by words so a sparse page cannot swing the document's score.
        scored = [(c, n) for c, n in confidences if c >= 0 and n > 0]
        total_words = sum(n for _, n in scored)
        confidence = (
            sum(c * n for c, n in scored) / total_words if total_words else -1.0
        )

        if 0 <= confidence < self._settings.ocr_low_confidence_threshold:
            warnings.append(
                "Some text may have been difficult to recognize. "
                "Please check the result against the original."
            )

        return OcrDocumentResult(
            markdown=markdown.strip(),
            confidence=confidence,
            word_count=word_count,
            pages=pages,
            provider=provider.name,
            languages=languages,
            warnings=list(dict.fromkeys(warnings)),
        )

    def recognize_image(
        self, path: Path, *, languages: str | None = None
    ) -> OcrDocumentResult:
        provider = self._require_provider()
        resolved, warnings = self.resolve_languages(languages)

        try:
            with Image.open(path) as opened:
                image = opened.convert("RGB") if opened.mode == "P" else opened.copy()
        except Exception as exc:
            raise CorruptFileError(f"could not open image: {exc}") from exc

        if not provider.provides_layout:
            prepared, _report = preprocess(image)
            result = provider.recognize(prepared, languages=resolved, page_number=1)
            warnings.extend(result.warnings)
            return self._finish(
                markdown=result.markdown,
                confidences=[(result.confidence, result.word_count)],
                word_count=result.word_count,
                pages=1,
                provider=provider,
                languages=resolved,
                warnings=warnings,
            )

        prepared, words = self._prepare_and_extract(provider, image, resolved)
        if not words:
            warnings.append("No readable text was found in this image.")
            return self._finish(
                markdown="",
                confidences=[],
                word_count=0,
                pages=1,
                provider=provider,
                languages=resolved,
                warnings=warnings,
            )

        markdown, layout_warnings = reconstruct(words, page_width=prepared.width)
        warnings.extend(layout_warnings)
        confidence = sum(w.confidence for w in words) / len(words)

        return self._finish(
            markdown=markdown,
            confidences=[(confidence, len(words))],
            word_count=len(words),
            pages=1,
            provider=provider,
            languages=resolved,
            warnings=warnings,
        )

    def recognize_pdf(
        self,
        path: Path,
        *,
        languages: str | None = None,
        pages: list[int] | None = None,
        should_cancel: object = None,
    ) -> OcrDocumentResult:
        provider = self._require_provider()
        resolved, warnings = self.resolve_languages(languages)
        settings = self._settings

        rendered = render_pages(
            path,
            dpi=settings.ocr_dpi,
            max_pages=settings.ocr_max_pages,
            pages=pages,
        )

        if provider.provides_layout:
            return self._recognize_pdf_with_layout(
                rendered,
                provider=provider,
                languages=resolved,
                warnings=warnings,
                should_cancel=should_cancel,
            )

        sections: list[str] = []
        confidences: list[tuple[float, int]] = []
        total_words = page_count = 0

        for page_number, image in rendered:
            if callable(should_cancel) and should_cancel():
                break
            prepared, _ = preprocess(image)
            result = provider.recognize(
                prepared, languages=resolved, page_number=page_number
            )
            page_count += 1
            if not result.is_empty:
                sections.append(result.markdown)
            confidences.append((result.confidence, result.word_count))
            total_words += result.word_count
            warnings.extend(result.warnings)

        return self._finish(
            markdown="\n\n".join(sections),
            confidences=confidences,
            word_count=total_words,
            pages=page_count,
            provider=provider,
            languages=resolved,
            warnings=warnings,
        )

    def _recognize_pdf_with_layout(
        self,
        rendered,
        *,
        provider: OcrProvider,
        languages: str,
        warnings: list[str],
        should_cancel: object = None,
    ) -> OcrDocumentResult:
        """Two-phase path: recognise every page, then lay them all out together."""
        recognised: list[tuple[int, list[OcrWord], int]] = []

        for page_number, image in rendered:
            if callable(should_cancel) and should_cancel():
                break
            prepared, words = self._prepare_and_extract(provider, image, languages)
            recognised.append((page_number, words, prepared.width))

        all_lines = [
            line
            for _, words, _ in recognised
            if words
            for line in build_lines(words)
        ]
        # One body-text size for the whole document keeps heading levels stable.
        document_body_height = body_text_height(all_lines) if all_lines else 0.0

        sections: list[str] = []
        confidences: list[tuple[float, int]] = []
        total_words = 0
        empty_pages = 0

        for _page_number, words, width in recognised:
            if not words:
                empty_pages += 1
                continue
            markdown, page_warnings = reconstruct(
                words, page_width=width, body_height=document_body_height
            )
            if markdown.strip():
                sections.append(markdown)
            warnings.extend(page_warnings)
            confidences.append(
                (sum(w.confidence for w in words) / len(words), len(words))
            )
            total_words += len(words)

        if empty_pages and recognised:
            warnings.append(
                f"{empty_pages} of {len(recognised)} pages contained no readable text."
            )

        return self._finish(
            markdown="\n\n".join(sections),
            confidences=confidences,
            word_count=total_words,
            pages=len(recognised),
            provider=provider,
            languages=languages,
            warnings=warnings,
        )
