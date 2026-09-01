"""Format detection that does not trust the filename.

A file called ``invoice.pdf`` is only treated as a PDF if its bytes actually
parse as one. Detection runs in four stages:

1. the declared extension must be a format we support at all;
2. binary signatures must match (magic bytes, at fixed offsets);
3. container formats are disambiguated by looking *inside* them, because
   .docx/.pptx/.xlsx/.epub/.zip share one signature, as do .doc/.xls/.ppt;
4. text formats, which have no signature, must actually parse.

Any inconsistency is a rejection, not a warning.
"""

from __future__ import annotations

import csv
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.conversion.errors import (
    CorruptFileError,
    FormatMismatchError,
    UnsupportedFormatError,
)
from app.conversion.registry import SupportedFormat, get_registry
from app.security.filenames import get_extension

HEADER_BYTES = 8192
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_TEXT_VALIDATION_LIMIT = 512 * 1024

# Extensions that name the same underlying format.
_ALIASES: dict[str, str] = {
    ".jpeg": ".jpg",
    ".htm": ".html",
}

# Marker entries that identify an OOXML container from inside the zip.
_ZIP_MARKERS: tuple[tuple[str, str], ...] = (
    ("word/document.xml", ".docx"),
    ("ppt/presentation.xml", ".pptx"),
    ("xl/workbook.xml", ".xlsx"),
)
_OLE_MARKERS: tuple[tuple[str, str], ...] = (
    ("worddocument", ".doc"),
    ("workbook", ".xls"),
    ("book", ".xls"),
    ("powerpoint document", ".ppt"),
)
_IMAGE_EXPECTED = {".jpg": "jpeg", ".png": "png", ".webp": "webp"}

# Formats a user will plausibly try that the engine genuinely cannot read.
# Saying so specifically is far more useful than "unsupported file type".
_UNSUPPORTED_HINTS: dict[str, str] = {
    ".doc": (
        "Older .doc files aren't supported. Open it in Word and save as .docx, "
        "then try again."
    ),
    ".ppt": (
        "Older .ppt files aren't supported. Open it in PowerPoint and save as "
        ".pptx, then try again."
    ),
    ".rtf": "RTF isn't supported. Save the document as .docx and try again.",
    ".pages": "Apple Pages files aren't supported. Export as .docx or .pdf.",
    ".key": "Apple Keynote files aren't supported. Export as .pptx or .pdf.",
    ".numbers": "Apple Numbers files aren't supported. Export as .xlsx or .csv.",
    ".odt": "OpenDocument text isn't supported. Save as .docx and try again.",
    ".txt": "Plain text is already readable as-is, so there's nothing to convert.",
    ".md": "This is already Markdown.",
}


def canonical(extension: str) -> str:
    """Collapse alias extensions onto one canonical spelling."""
    ext = extension.lower()
    return _ALIASES.get(ext, ext)


@dataclass
class DetectionResult:
    """What the file actually is, alongside what it claimed to be."""

    format: SupportedFormat
    declared_extension: str
    detected_extension: str
    charset: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def extension(self) -> str:
        return self.format.extension


def read_header(path: Path, size: int = HEADER_BYTES) -> bytes:
    with path.open("rb") as fh:
        return fh.read(size)


def _looks_like_zip(header: bytes) -> bool:
    return any(header.startswith(sig) for sig in _ZIP_SIGNATURES)


def _inspect_zip_container(path: Path) -> str:
    """Return the real extension for a zip-based file."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "mimetype" in names:
                try:
                    if zf.read("mimetype")[:64].strip() == b"application/epub+zip":
                        return ".epub"
                except (KeyError, RuntimeError, zipfile.BadZipFile):
                    pass
            for marker, ext in _ZIP_MARKERS:
                if marker in names:
                    return ext
            # No recognised marker: it is a plain archive we walk file-by-file.
            return ".zip"
    except zipfile.BadZipFile as exc:
        raise CorruptFileError(str(exc)) from exc


def _inspect_ole_container(path: Path) -> str:
    """Return the real extension for a legacy OLE2 Office file."""
    try:
        import olefile
    except ImportError:  # pragma: no cover - ships with markitdown[all]
        return ""
    try:
        with olefile.OleFileIO(str(path)) as ole:
            entries = {"/".join(part).lower() for part in ole.listdir()}
    except Exception as exc:
        raise CorruptFileError(str(exc)) from exc
    for marker, ext in _OLE_MARKERS:
        if marker in entries:
            return ext
    return ""


def _detect_charset(sample: bytes) -> str:
    """Best-effort charset for text formats, defaulting to UTF-8."""
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        sample.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(sample).best()
        if best is not None and best.encoding:
            return best.encoding
    except Exception:
        pass
    return "utf-8"


def _decode(path: Path, charset: str, limit: int = _TEXT_VALIDATION_LIMIT) -> str:
    with path.open("rb") as fh:
        raw = fh.read(limit)
    return raw.decode(charset, errors="replace")


def _validate_json_like(path: Path, ext: str, text: str) -> None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        # A truncated read of a large but valid file is not a failure.
        if path.stat().st_size > _TEXT_VALIDATION_LIMIT:
            return
        raise FormatMismatchError(f"not valid JSON: {exc.msg}") from exc
    if ext == ".ipynb" and not (isinstance(parsed, dict) and "cells" in parsed):
        raise FormatMismatchError("JSON file is not a Jupyter notebook")


def _validate_xml(path: Path, text: str) -> None:
    if not text.lstrip().startswith("<"):
        raise FormatMismatchError("file does not start with an XML element")
    if path.stat().st_size > _TEXT_VALIDATION_LIMIT:
        return
    from defusedxml.ElementTree import fromstring

    try:
        fromstring(text)
    except Exception as exc:
        raise FormatMismatchError(f"not well-formed XML: {exc}") from exc


def _validate_text_format(path: Path, ext: str, charset: str) -> None:
    """Parse text-based formats so malformed content is rejected up front."""
    text = _decode(path, charset)
    if not text.strip():
        raise CorruptFileError("file is empty")

    if ext in (".json", ".ipynb"):
        _validate_json_like(path, ext, text)
    elif ext == ".xml":
        _validate_xml(path, text)
    elif ext == ".html":
        if "<" not in text[:4096]:
            raise FormatMismatchError("file contains no HTML markup")
    elif ext == ".csv":
        sample = text[:8192]
        try:
            csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            # Single-column CSV is legal and unsniffable, so only the empty
            # case is a real failure here.
            if not sample.strip():
                raise CorruptFileError("file is empty") from None


def _validate_image(path: Path, ext: str) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            actual = (img.format or "").lower()
    except UnidentifiedImageError as exc:
        raise FormatMismatchError("file is not a readable image") from exc
    except Exception as exc:
        raise CorruptFileError(str(exc)) from exc

    expected = _IMAGE_EXPECTED[canonical(ext)]
    if actual != expected:
        raise FormatMismatchError(f"image is {actual.upper()}, not {expected.upper()}")


def detect_format(path: Path, declared_filename: str | None) -> DetectionResult:
    """Identify ``path``, cross-checking its declared name against its bytes."""
    registry = get_registry()
    declared_ext = get_extension(declared_filename)
    fmt = registry.by_extension(declared_ext)
    if fmt is None:
        hint = _UNSUPPORTED_HINTS.get(declared_ext)
        raise UnsupportedFormatError(
            f"unsupported extension {declared_ext or '(none)'}",
            # A specific next step beats "this file type isn't supported".
            message=hint or UnsupportedFormatError.message,
        )

    if path.stat().st_size == 0:
        raise CorruptFileError("file is empty")

    header = read_header(path)

    for signature in fmt.signatures:
        if not signature.matches(header):
            raise FormatMismatchError(f"content does not match a {fmt.label} file")

    declared_canonical = canonical(declared_ext)
    detected_ext = declared_canonical

    if _looks_like_zip(header):
        real = _inspect_zip_container(path)
        if declared_canonical != real:
            real_fmt = registry.by_extension(real)
            real_label = real_fmt.label if real_fmt else real.lstrip(".").upper()
            raise FormatMismatchError(
                f"file is really {real_label}, not {fmt.label}"
            )
        detected_ext = real

    elif header.startswith(_OLE_SIGNATURE):
        real = _inspect_ole_container(path)
        if real and declared_canonical != real:
            raise FormatMismatchError(
                f"file is really {real.lstrip('.').upper()}, not {fmt.label}"
            )
        detected_ext = real or declared_canonical

    charset: str | None = None
    if fmt.is_text_based:
        charset = _detect_charset(header)
        _validate_text_format(path, declared_canonical, charset)
    elif fmt.category == "images":
        _validate_image(path, declared_ext)

    return DetectionResult(
        format=fmt,
        declared_extension=declared_ext,
        detected_extension=detected_ext,
        charset=charset,
    )
