"""The OCR provider interface.

Providers are interchangeable and selected at runtime by availability and
configuration, so the rest of the pipeline never needs to know whether text
came from Tesseract or a hosted vision model.

    OcrProvider
    ├── TesseractOcrProvider   local, default, English + Bengali
    └── VisionOcrProvider      optional, requires explicit configuration
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL.Image import Image

from app.ocr.types import OcrPageResult, OcrWord


class OcrProvider(ABC):
    """Recognises text in an image and returns Markdown."""

    #: Stable identifier reported in result metadata and health checks.
    name: str = "ocr"

    #: Whether the provider returns positioned words. Providers that do let the
    #: caller reconstruct structure across a whole document at once - which is
    #: how heading levels stay consistent from page 1 to page 40 - instead of
    #: each page being laid out in isolation.
    provides_layout: bool = False

    def orient(self, image: Image) -> tuple[Image, int]:
        """Return the page the right way up, plus the rotation applied."""
        return image, 0

    def extract_words(self, image: Image, *, languages: str) -> list[OcrWord]:
        """Positioned words for one page. Only valid when ``provides_layout``."""
        raise NotImplementedError(
            f"{type(self).__name__} does not provide word-level layout"
        )

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can run right now (binaries, keys, models)."""

    @abstractmethod
    def supported_languages(self) -> list[str]:
        """Language codes this provider can currently recognise."""

    @abstractmethod
    def recognize(
        self, image: Image, *, languages: str, page_number: int = 1
    ) -> OcrPageResult:
        """Recognise one page image and return reconstructed Markdown."""

    def describe(self) -> dict[str, object]:
        """Diagnostic summary for the readiness endpoint."""
        available = self.is_available()
        return {
            "name": self.name,
            "available": available,
            "languages": self.supported_languages() if available else [],
        }
