"""Adapter around Microsoft MarkItDown.

The rest of the application talks to this class, never to MarkItDown directly,
so the upstream library can be upgraded or swapped without touching the API,
the OCR pipeline or the job runner.

Verified against **markitdown 0.1.7**. That version supplies converters for
PDF, DOCX, PPTX, XLSX/XLS, HTML, CSV, EPUB, ZIP, images and more, but has no
JSON or generic-XML converter and drops notebook outputs, so we register three
converters of our own ahead of the built-ins.

Two capabilities MarkItDown does *not* provide are handled elsewhere: it has no
OCR (its ``ImageConverter`` only reads EXIF metadata and, optionally, calls a
vision LLM) and its ``PdfConverter`` is text-only. See ``app/ocr``.
"""

from __future__ import annotations

from pathlib import Path

from markitdown import (
    FileConversionException,
    MarkItDown,
    MissingDependencyException,
    StreamInfo,
    UnsupportedFormatException,
)

from app.config import Settings
from app.conversion.errors import (
    ConversionError,
    CorruptFileError,
    UnsupportedFormatError,
)
from app.conversion.result import RawConversion
from app.converters.ipynb_converter import IpynbConverter
from app.converters.json_converter import JsonConverter
from app.converters.xml_converter import XmlConverter
from app.logging_setup import get_logger

logger = get_logger(__name__)

# Lower values are tried first in MarkItDown, and its own specific converters
# sit at 0.0, so a negative priority puts ours ahead of them.
_OVERRIDE_PRIORITY = -1.0

MIME_BY_EXTENSION: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".doc": "application/msword",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".ipynb": "application/x-ipynb+json",
    ".epub": "application/epub+zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".zip": "application/zip",
}


class MarkItDownAdapter:
    """Thin, defensive wrapper over the MarkItDown engine."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = MarkItDown(
            enable_builtins=True,
            enable_plugins=settings.markitdown_plugins_enabled,
        )
        # Registered after construction so they take precedence over built-ins.
        for converter in (JsonConverter(), XmlConverter(), IpynbConverter()):
            self._engine.register_converter(converter, priority=_OVERRIDE_PRIORITY)

        if settings.markitdown_plugins_enabled:
            logger.warning(
                "markitdown third-party plugins are enabled",
                extra={"plugins_enabled": True},
            )

    @property
    def engine_version(self) -> str:
        from importlib.metadata import version

        try:
            return version("markitdown")
        except Exception:  # pragma: no cover - metadata always present in practice
            return "unknown"

    def convert(
        self,
        path: Path,
        *,
        extension: str,
        filename: str | None = None,
        charset: str | None = None,
    ) -> RawConversion:
        """Convert a local file, translating engine errors into ours.

        ``extension`` is the *verified* extension from content detection, not
        whatever the upload claimed, so MarkItDown dispatches on what the file
        actually is.
        """
        stream_info = StreamInfo(
            extension=extension,
            mimetype=MIME_BY_EXTENSION.get(extension),
            charset=charset,
            # Deliberately no local_path/url: nothing here should leak a server
            # path into converter output or error messages.
            filename=filename,
        )

        try:
            result = self._engine.convert_local(str(path), stream_info=stream_info)
        except UnsupportedFormatException as exc:
            raise UnsupportedFormatError(str(exc)) from exc
        except MissingDependencyException as exc:
            logger.error(
                "converter dependency missing",
                extra={"format": extension},
                exc_info=True,
            )
            raise ConversionError(
                str(exc),
                message="Support for this file type isn't available on the server.",
            ) from exc
        except FileConversionException as exc:
            raise CorruptFileError(str(exc)) from exc
        except ConversionError:
            raise
        except Exception as exc:
            # Malformed documents surface as arbitrary parser exceptions.
            raise CorruptFileError(f"{type(exc).__name__}: {exc}") from exc

        return RawConversion(markdown=result.markdown or "", title=result.title)
