"""Tesseract-backed OCR provider.

Tesseract is the default local engine because it covers both required
languages well (``eng`` and ``ben``), needs no GPU, ships as a small OS package
rather than a multi-gigabyte model download, and is Apache-2.0 licensed.

It is asked for *positioned* output (``image_to_data``) rather than plain text,
because the coordinates are what make structure reconstruction possible.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from PIL.Image import Image

from app.config import Settings
from app.logging_setup import get_logger
from app.ocr.base import OcrProvider
from app.ocr.layout import body_text_height, build_lines, reconstruct
from app.ocr.types import OcrPageResult, OcrWord

logger = get_logger(__name__)

# Layout analysis with orientation detection; LSTM engine.
DEFAULT_CONFIG = "--oem 3 --psm 3"
# Tesseract reports -1 for non-text boxes.
MIN_WORD_CONFIDENCE = 0.0
_OSD_ROTATE = re.compile(r"Rotate:\s*(\d+)")
_OSD_CONFIDENCE = re.compile(r"Orientation confidence:\s*([\d.]+)")
MIN_OSD_CONFIDENCE = 1.5


class TesseractOcrProvider(OcrProvider):
    name = "tesseract"
    provides_layout = True

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._configure()

    def _configure(self) -> None:
        """Point pytesseract at the binary and language data."""
        try:
            import pytesseract
        except ImportError:  # pragma: no cover - declared dependency
            return

        if self._settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._settings.tesseract_cmd
        if self._settings.tessdata_prefix:
            os.environ["TESSDATA_PREFIX"] = self._settings.tessdata_prefix

    # --- availability ----------------------------------------------------

    def is_available(self) -> bool:
        return bool(self.supported_languages())

    @lru_cache(maxsize=1)  # noqa: B019 - one provider instance per process
    def _languages(self) -> tuple[str, ...]:
        try:
            import pytesseract

            langs = pytesseract.get_languages(config="")
        except Exception as exc:
            logger.warning(
                "tesseract is unavailable", extra={"error_message": str(exc)}
            )
            return ()
        return tuple(sorted(lang for lang in langs if lang != "osd"))

    def supported_languages(self) -> list[str]:
        return list(self._languages())

    def resolve_languages(self, requested: str) -> tuple[str, list[str]]:
        """Map a requested language string onto what is actually installed.

        Returns the usable ``lang`` string plus any warnings, so a missing
        language pack degrades to a warning instead of a hard failure.
        """
        available = set(self._languages())
        if not available:
            return "", ["OCR language data is not installed on the server."]

        wanted = [part for part in requested.split("+") if part]
        usable = [part for part in wanted if part in available]
        missing = [part for part in wanted if part not in available]

        warnings: list[str] = []
        if missing:
            warnings.append(
                "OCR language data for "
                + ", ".join(sorted(missing))
                + " isn't installed, so those languages were skipped."
            )
        if not usable:
            fallback = "eng" if "eng" in available else sorted(available)[0]
            usable = [fallback]
        return "+".join(usable), warnings

    # --- recognition -----------------------------------------------------

    def orient(self, image: Image) -> tuple[Image, int]:
        """Upright the page using Tesseract's orientation-detection model."""
        degrees = self._detect_rotation(image)
        if degrees:
            # OSD reports the clockwise rotation needed to upright the page.
            image = image.rotate(-degrees, expand=True, fillcolor=255)
        return image, degrees

    def _detect_rotation(self, image: Image) -> int:
        """Ask Tesseract's OSD model whether the page is rotated 90/180/270."""
        try:
            import pytesseract

            osd = pytesseract.image_to_osd(image, config="--psm 0")
        except Exception:
            # OSD fails routinely on sparse pages; that is not an error.
            return 0

        rotate_match = _OSD_ROTATE.search(osd)
        confidence_match = _OSD_CONFIDENCE.search(osd)
        if not rotate_match or not confidence_match:
            return 0
        if float(confidence_match.group(1)) < MIN_OSD_CONFIDENCE:
            return 0
        return int(rotate_match.group(1)) % 360

    def extract_words(self, image: Image, *, languages: str) -> list[OcrWord]:
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(
            image,
            lang=languages,
            config=DEFAULT_CONFIG,
            output_type=Output.DICT,
        )

        words: list[OcrWord] = []
        for index, text in enumerate(data["text"]):
            cleaned = (text or "").strip()
            if not cleaned:
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                continue
            if confidence < MIN_WORD_CONFIDENCE:
                continue
            words.append(
                OcrWord(
                    text=cleaned,
                    left=int(data["left"][index]),
                    top=int(data["top"][index]),
                    width=int(data["width"][index]),
                    height=int(data["height"][index]),
                    confidence=confidence,
                    block=int(data["block_num"][index]),
                    paragraph=int(data["par_num"][index]),
                    line=int(data["line_num"][index]),
                )
            )
        return words

    def recognize(
        self,
        image: Image,
        *,
        languages: str,
        page_number: int = 1,
        body_height: float | None = None,
        detect_orientation: bool = True,
    ) -> OcrPageResult:
        warnings: list[str] = []
        rotated = 0

        if detect_orientation:
            image, rotated = self.orient(image)

        words = self.extract_words(image, languages=languages)
        if not words:
            return OcrPageResult(
                markdown="",
                confidence=0.0,
                word_count=0,
                page_number=page_number,
                rotated_degrees=rotated,
                warnings=["No readable text was found on this page."],
            )

        markdown, layout_warnings = reconstruct(
            words, page_width=image.width, body_height=body_height
        )
        warnings.extend(layout_warnings)
        confidence = sum(w.confidence for w in words) / len(words)

        return OcrPageResult(
            markdown=markdown,
            confidence=confidence,
            word_count=len(words),
            page_number=page_number,
            rotated_degrees=rotated,
            warnings=warnings,
        )

    def measure_body_height(self, image: Image, languages: str) -> float:
        """Body-text height for one page, used to align headings document-wide."""
        words = self.extract_words(image, languages=languages)
        return body_text_height(build_lines(words)) if words else 0.0
