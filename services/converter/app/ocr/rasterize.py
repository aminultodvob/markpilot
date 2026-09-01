"""Rendering PDF pages to images for OCR.

Uses **pypdfium2**, which wraps Google's PDFium. Chosen over the common
alternatives on licensing and deployment grounds: PyMuPDF is AGPL-3.0 (a poor
fit for a hosted service), and pdf2image shells out to a Poppler binary that
must be installed separately. pypdfium2 is Apache-2.0/BSD-3 and ships a
self-contained wheel.

Pages are rendered and yielded one at a time. A 300-DPI page is roughly 25 MB
as RGB, so materialising a whole document at once is how an OCR service runs
out of memory on a large scan.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from app.conversion.errors import CorruptFileError
from app.logging_setup import get_logger

logger = get_logger(__name__)

BASE_DPI = 72.0
MAX_RENDER_DIMENSION = 5000


@contextmanager
def _open_document(path: Path):
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise CorruptFileError(f"could not open PDF: {exc}") from exc
    try:
        yield document
    finally:
        with contextlib.suppress(Exception):  # close is best effort
            document.close()


def page_count(path: Path) -> int:
    """Number of pages, or 0 if the document cannot be opened."""
    try:
        with _open_document(path) as document:
            return len(document)
    except CorruptFileError:
        return 0


def _scale_for(dpi: int, width_pt: float, height_pt: float) -> float:
    """DPI scale, clamped so an outsized page cannot allocate a huge bitmap."""
    scale = dpi / BASE_DPI
    longest = max(width_pt, height_pt) * scale
    if longest > MAX_RENDER_DIMENSION:
        scale *= MAX_RENDER_DIMENSION / longest
    return scale


def render_pages(
    path: Path,
    *,
    dpi: int = 300,
    max_pages: int = 100,
    pages: list[int] | None = None,
) -> Iterator[tuple[int, Image.Image]]:
    """Yield ``(page_number, image)`` for each requested page, one at a time.

    ``pages`` is a 1-based list; ``None`` means every page up to ``max_pages``.
    """
    with _open_document(path) as document:
        total = len(document)
        if total == 0:
            raise CorruptFileError("PDF contains no pages")

        wanted = (
            [p for p in pages if 1 <= p <= total]
            if pages is not None
            else list(range(1, total + 1))
        )[:max_pages]

        for page_number in wanted:
            page = document[page_number - 1]
            try:
                scale = _scale_for(dpi, page.get_width(), page.get_height())
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    # Detach from the bitmap buffer before it is released.
                    yield page_number, image.copy()
                finally:
                    bitmap.close()
            except CorruptFileError:
                raise
            except Exception as exc:
                logger.warning(
                    "failed to render PDF page",
                    extra={"page": page_number, "error_message": str(exc)},
                )
                continue
            finally:
                with contextlib.suppress(Exception):
                    page.close()
