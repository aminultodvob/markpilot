"""Filename sanitization.

Uploaded filenames are never used to build filesystem paths - every file on
disk gets a random opaque id. These helpers exist purely to produce a *safe
display and download name*, so a hostile filename cannot escape a directory,
poison a Content-Disposition header, or turn into a shell/Windows special name.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath, PureWindowsPath

MAX_STEM_LENGTH = 120

# C0/C1 control characters plus the separators and shell/HTTP-hostile chars.
_ILLEGAL = re.compile(r'[\x00-\x1f\x7f-\x9f<>:"/\|?*]')
_COLLAPSE = re.compile(r"\s+")
# Windows device names are unusable as filenames regardless of extension.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
FALLBACK_STEM = "document"


def strip_directories(name: str) -> str:
    """Remove any path component, treating the input as both POSIX and Windows."""
    name = name.replace("\x00", "")
    # Handle mixed separators: take the last component under both conventions.
    name = PureWindowsPath(PurePosixPath(name).name).name
    return name


def sanitize_filename(name: str | None, *, fallback: str = FALLBACK_STEM) -> str:
    """Return a safe, human-recognisable filename.

    Guarantees the result contains no path separators, no control characters,
    no leading dots, is not a Windows reserved device name, and is non-empty.
    """
    if not name:
        return fallback

    name = strip_directories(name)
    # Normalise so visually-identical Unicode can't produce two "different" names.
    name = unicodedata.normalize("NFC", name)
    name = _ILLEGAL.sub("_", name)
    name = _COLLAPSE.sub(" ", name).strip()
    # Leading dots hide files; trailing dots/spaces are stripped by Windows.
    name = name.lstrip(".").rstrip(". ")

    if not name:
        return fallback

    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""

    if stem.lower() in _RESERVED:
        stem = f"{stem}_file"
    if not stem:
        stem = fallback
    if len(stem) > MAX_STEM_LENGTH:
        stem = stem[:MAX_STEM_LENGTH].rstrip(". ")

    ext = _ILLEGAL.sub("", ext)[:16]
    return f"{stem}.{ext}" if ext else stem


def get_extension(name: str | None) -> str:
    """Lowercased extension including the dot, or '' when there is none."""
    safe = sanitize_filename(name)
    _, dot, ext = safe.rpartition(".")
    return f".{ext.lower()}" if dot and ext else ""


def markdown_name(original: str | None) -> str:
    """Map an input filename onto its Markdown output name."""
    safe = sanitize_filename(original)
    stem, dot, _ = safe.rpartition(".")
    return f"{stem or safe}.md" if dot else f"{safe}.md"


def dedupe_name(name: str, taken: set[str]) -> str:
    """Return ``name``, suffixed if needed, so it is unique within ``taken``."""
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    counter = 2
    while True:
        candidate = f"{stem}-{counter}.{ext}" if ext else f"{stem}-{counter}"
        if candidate not in taken:
            return candidate
        counter += 1


def header_safe(name: str) -> str:
    """ASCII-only fallback for the legacy Content-Disposition filename field."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    ascii_name = _ILLEGAL.sub("_", ascii_name).replace(",", "_").replace(";", "_").strip()

    stem, dot, ext = ascii_name.rpartition(".")
    if not dot:
        stem, ext = ascii_name, ""
    # A fully non-ASCII name (e.g. Bengali) leaves an empty stem behind.
    stem = stem.strip(". ") or "download"
    return f"{stem}.{ext}" if ext else stem
