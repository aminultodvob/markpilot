"""Central format registry.

The registry is loaded from ``packages/formats/formats.json``, the single
source of truth shared with the web app. Nothing else in the codebase should
hard-code a list of supported extensions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_ENV_OVERRIDE = "FORMATS_REGISTRY_PATH"
_RELATIVE_CANDIDATES = (
    Path("packages/formats/formats.json"),
    Path("formats/formats.json"),
    Path("formats.json"),
)


@dataclass(frozen=True)
class Signature:
    offset: int
    hex: str

    @property
    def raw(self) -> bytes:
        return bytes.fromhex(self.hex)

    def matches(self, header: bytes) -> bool:
        end = self.offset + len(self.raw)
        if len(header) < end:
            return False
        return header[self.offset : end] == self.raw


@dataclass(frozen=True)
class SupportedFormat:
    extension: str
    label: str
    category: str
    icon: str
    mime_types: tuple[str, ...]
    signatures: tuple[Signature, ...]
    ocr_capable: bool

    @property
    def is_text_based(self) -> bool:
        """Text formats have no binary signature and are validated by parsing."""
        return not self.signatures


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    description: str


class FormatRegistry:
    def __init__(self, formats: list[SupportedFormat], categories: list[Category]):
        self._formats = formats
        self._categories = categories
        self._by_extension = {f.extension: f for f in formats}
        self._by_mime: dict[str, list[SupportedFormat]] = {}
        for fmt in formats:
            for mime in fmt.mime_types:
                self._by_mime.setdefault(mime, []).append(fmt)

    @property
    def formats(self) -> list[SupportedFormat]:
        return list(self._formats)

    @property
    def categories(self) -> list[Category]:
        return list(self._categories)

    @property
    def extensions(self) -> set[str]:
        return set(self._by_extension)

    def by_extension(self, extension: str) -> SupportedFormat | None:
        return self._by_extension.get(extension.lower())

    def by_mime(self, mime: str) -> list[SupportedFormat]:
        return list(self._by_mime.get(mime.split(";")[0].strip().lower(), []))

    def is_supported(self, extension: str) -> bool:
        return extension.lower() in self._by_extension

    def formats_in_category(self, category_id: str) -> list[SupportedFormat]:
        return [f for f in self._formats if f.category == category_id]


def _locate_registry_file() -> Path:
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise FileNotFoundError(f"{_ENV_OVERRIDE} points at a missing file: {path}")

    # Walk up from this module so the registry resolves from the repo checkout,
    # then fall back to cwd-relative paths used inside the container image.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "packages" / "formats" / "formats.json"
        if candidate.is_file():
            return candidate
    for candidate in _RELATIVE_CANDIDATES:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Could not locate formats.json format registry")


@lru_cache
def get_registry() -> FormatRegistry:
    data = json.loads(_locate_registry_file().read_text(encoding="utf-8"))
    formats = [
        SupportedFormat(
            extension=item["extension"].lower(),
            label=item["label"],
            category=item["category"],
            icon=item["icon"],
            mime_types=tuple(m.lower() for m in item["mimeTypes"]),
            signatures=tuple(
                Signature(offset=s["offset"], hex=s["hex"].lower())
                for s in item["signatures"]
            ),
            ocr_capable=bool(item["ocrCapable"]),
        )
        for item in data["formats"]
    ]
    categories = [
        Category(id=c["id"], label=c["label"], description=c["description"])
        for c in data["categories"]
    ]
    known = {c.id for c in categories}
    unknown = {f.category for f in formats} - known
    if unknown:
        raise ValueError(f"formats.json references unknown categories: {sorted(unknown)}")
    return FormatRegistry(formats, categories)
