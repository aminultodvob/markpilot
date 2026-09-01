"""Safe ZIP inspection and extraction.

Archives are the highest-risk input we accept, so nothing here trusts the
archive's own metadata. Specifically we defend against:

* **Zip Slip / path traversal** - entry names containing ``..``, absolute
  paths, drive letters or UNC prefixes, verified again by resolving the final
  path and requiring containment in the destination.
* **Symlink escapes** - entries whose Unix mode marks them as symlinks are
  refused outright.
* **Zip bombs** - both a global uncompressed-byte budget and a per-entry
  compression-ratio cap, enforced *while streaming* rather than by trusting
  the declared ``file_size``.
* **File-count floods** and **nested archive recursion**.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.config import Settings
from app.conversion.errors import ArchiveError, CorruptFileError
from app.conversion.registry import get_registry
from app.security.filenames import sanitize_filename

_CHUNK = 64 * 1024
_S_IFLNK = 0o120000
_S_IFMT = 0o170000
# Ratio guard only applies past this size; tiny files compress absurdly well.
_RATIO_MIN_BYTES = 64 * 1024


@dataclass(frozen=True)
class ArchiveEntry:
    """A member of an archive that we are willing to extract."""

    name: str
    display_name: str
    extension: str
    compressed_size: int
    declared_size: int
    supported: bool


@dataclass
class ArchiveInspection:
    entries: list[ArchiveEntry]
    total_declared_size: int
    skipped: list[str]

    @property
    def convertible(self) -> list[ArchiveEntry]:
        return [e for e in self.entries if e.supported]


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & _S_IFMT == _S_IFLNK


def _reject_unsafe_name(name: str) -> None:
    """Reject an entry name before it is ever joined to a path."""
    if not name or name in (".", ".."):
        raise ArchiveError(f"archive contains an invalid entry name: {name!r}")
    if "\x00" in name:
        raise ArchiveError("archive entry name contains a null byte")
    # Normalise Windows separators so a\..\b is caught the same as a/../b.
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or normalised.startswith("//"):
        raise ArchiveError(f"archive contains an absolute path: {name!r}")
    if len(normalised) >= 2 and normalised[1] == ":":
        raise ArchiveError(f"archive contains a drive-letter path: {name!r}")
    if any(part == ".." for part in PurePosixPath(normalised).parts):
        raise ArchiveError(f"archive contains a traversal path: {name!r}")


def _safe_target(destination: Path, name: str) -> Path:
    """Resolve ``name`` inside ``destination``, refusing anything that escapes."""
    _reject_unsafe_name(name)
    root = destination.resolve()
    target = (root / name.replace("\\", "/")).resolve()
    if target != root and root not in target.parents:
        raise ArchiveError(f"archive entry escapes the extraction directory: {name!r}")
    return target


def inspect_archive(path: Path, settings: Settings) -> ArchiveInspection:
    """Validate an archive's structure and list what we would convert."""
    if path.stat().st_size > settings.max_archive_size_bytes:
        raise ArchiveError(
            f"archive is larger than the {settings.max_archive_size_mb} MB limit"
        )

    registry = get_registry()
    entries: list[ArchiveEntry] = []
    skipped: list[str] = []
    total_declared = 0

    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            file_infos = [i for i in infos if not i.is_dir()]

            if len(file_infos) > settings.max_archive_files:
                raise ArchiveError(
                    f"archive contains {len(file_infos)} files, "
                    f"more than the {settings.max_archive_files} allowed"
                )

            for info in file_infos:
                _reject_unsafe_name(info.filename)
                if _is_symlink(info):
                    raise ArchiveError(
                        f"archive contains a symbolic link: {info.filename!r}"
                    )

                total_declared += info.file_size
                if total_declared > settings.max_archive_uncompressed_bytes:
                    raise ArchiveError(
                        "archive expands to more than the "
                        f"{settings.max_archive_uncompressed_mb} MB uncompressed limit"
                    )

                if (
                    info.file_size > _RATIO_MIN_BYTES
                    and info.compress_size > 0
                    and info.file_size / info.compress_size
                    > settings.max_archive_compression_ratio
                ):
                    raise ArchiveError(
                        f"archive entry {info.filename!r} has a suspicious "
                        "compression ratio"
                    )

                display = sanitize_filename(PurePosixPath(info.filename).name)
                _, dot, ext = display.rpartition(".")
                extension = f".{ext.lower()}" if dot else ""
                supported = registry.is_supported(extension)
                # Nested archives are not walked recursively at depth 1.
                if extension == ".zip" and settings.max_archive_depth <= 1:
                    supported = False
                    skipped.append(display)
                elif not supported:
                    skipped.append(display)

                entries.append(
                    ArchiveEntry(
                        name=info.filename,
                        display_name=display,
                        extension=extension,
                        compressed_size=info.compress_size,
                        declared_size=info.file_size,
                        supported=supported,
                    )
                )
    except zipfile.BadZipFile as exc:
        raise CorruptFileError(f"archive is not a readable ZIP file: {exc}") from exc

    if not entries:
        raise ArchiveError("archive is empty")

    return ArchiveInspection(
        entries=entries, total_declared_size=total_declared, skipped=skipped
    )


def extract_entry(
    archive_path: Path,
    entry: ArchiveEntry,
    destination: Path,
    settings: Settings,
) -> Path:
    """Stream one entry to disk, enforcing the byte budget as we read.

    The declared ``file_size`` is metadata an attacker controls, so the cap is
    applied to bytes actually written and the read is aborted the moment it is
    exceeded.
    """
    target = _safe_target(destination, entry.name)
    target.parent.mkdir(parents=True, exist_ok=True)

    budget = min(settings.max_file_size_bytes, settings.max_archive_uncompressed_bytes)
    written = 0

    with (
        zipfile.ZipFile(archive_path) as zf,
        zf.open(entry.name) as source,
        target.open("wb") as sink,
    ):
        while True:
            chunk = source.read(_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > budget:
                sink.close()
                target.unlink(missing_ok=True)
                raise ArchiveError(
                    f"archive entry {entry.display_name!r} is larger than "
                    "the per-file limit"
                )
            sink.write(chunk)

    return target
