"""Security unit tests.

Each test here corresponds to an attack the service is expected to refuse:
path traversal through a filename, a file lying about its type, Zip Slip, zip
bombs, symlink escapes, and rate-limit evasion.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.conversion.errors import (
    ArchiveError,
    ConversionError,
    CorruptFileError,
    FormatMismatchError,
    UnsupportedFormatError,
)
from app.security.archive import extract_entry, inspect_archive
from app.security.detection import detect_format
from app.security.filenames import (
    dedupe_name,
    get_extension,
    header_safe,
    markdown_name,
    sanitize_filename,
)
from app.security.ratelimit import RateLimiter, client_key

# OLE2 compound-document signature, shared by legacy .doc/.xls/.ppt.
_OLE2_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")

# --- filenames --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
        ("/absolute/path/file.pdf", "file.pdf"),
        ("C:\\Users\\admin\\secret.docx", "secret.docx"),
        ("normal.pdf", "normal.pdf"),
        (".hidden", "hidden"),
        ("", "document"),
        (None, "document"),
    ],
)
def test_sanitize_strips_every_path_component(raw, expected):
    result = sanitize_filename(raw)
    assert result == expected
    assert "/" not in result and "\\" not in result
    assert not result.startswith(".")


@pytest.mark.parametrize("device", ["CON", "PRN", "AUX", "NUL", "COM1", "LPT9"])
def test_windows_reserved_device_names_are_defused(device):
    result = sanitize_filename(f"{device}.pdf")
    assert result.lower().split(".")[0] not in {
        "con", "prn", "aux", "nul", "com1", "lpt9",
    }


def test_control_characters_and_quotes_are_removed():
    result = sanitize_filename('re\x00port"; rm -rf /.pdf')
    assert "\x00" not in result
    assert '"' not in result


def test_unicode_filenames_survive_intact():
    assert sanitize_filename("প্রতিবেদন.pdf") == "প্রতিবেদন.pdf"
    assert markdown_name("প্রতিবেদন.pdf") == "প্রতিবেদন.md"


def test_header_safe_never_yields_an_empty_stem():
    # A fully non-ASCII name leaves nothing behind after transliteration.
    assert header_safe(markdown_name("প্রতিবেদন.pdf")) == "download.md"
    assert header_safe("café.md") == "cafe.md"


def test_long_names_are_truncated_but_keep_their_extension():
    result = sanitize_filename("a" * 400 + ".pdf")
    assert len(result) < 200
    assert result.endswith(".pdf")


def test_dedupe_avoids_collisions():
    assert dedupe_name("a.md", set()) == "a.md"
    assert dedupe_name("a.md", {"a.md"}) == "a-2.md"
    assert dedupe_name("a.md", {"a.md", "a-2.md"}) == "a-3.md"


def test_extension_is_taken_from_the_sanitized_name():
    assert get_extension("../../evil.PDF") == ".pdf"
    assert get_extension("noextension") == ""


# --- content detection ------------------------------------------------------


def test_valid_fixtures_are_detected_correctly(fixture):
    for name, expected in [
        ("text.pdf", ".pdf"),
        ("proposal.docx", ".docx"),
        ("deck.pptx", ".pptx"),
        ("workbook.xlsx", ".xlsx"),
        ("book.epub", ".epub"),
        ("bundle.zip", ".zip"),
        ("table.csv", ".csv"),
        ("records.json", ".json"),
        ("catalog.xml", ".xml"),
        ("page.html", ".html"),
        ("notebook.ipynb", ".ipynb"),
        ("ocr-english.png", ".png"),
        ("ocr-english.jpg", ".jpg"),
        ("ocr-english.webp", ".webp"),
    ]:
        path = fixture(name)
        assert detect_format(path, name).detected_extension == expected


def test_a_png_renamed_to_pdf_is_rejected(fixture, tmp_path):
    disguised = tmp_path / "invoice.pdf"
    disguised.write_bytes(fixture("ocr-english.png").read_bytes())
    with pytest.raises(FormatMismatchError):
        detect_format(disguised, "invoice.pdf")


def test_ooxml_containers_are_told_apart(fixture, tmp_path):
    """.docx/.pptx/.xlsx/.epub/.zip all share the ZIP signature."""
    disguised = tmp_path / "budget.xlsx"
    disguised.write_bytes(fixture("proposal.docx").read_bytes())
    with pytest.raises(FormatMismatchError, match="Word"):
        detect_format(disguised, "budget.xlsx")

    disguised = tmp_path / "report.docx"
    disguised.write_bytes(fixture("bundle.zip").read_bytes())
    with pytest.raises(FormatMismatchError):
        detect_format(disguised, "report.docx")


def test_image_formats_are_not_interchangeable(fixture, tmp_path):
    disguised = tmp_path / "photo.jpg"
    disguised.write_bytes(fixture("ocr-english.png").read_bytes())
    with pytest.raises(FormatMismatchError):
        detect_format(disguised, "photo.jpg")


def test_executables_and_unknown_types_are_rejected(tmp_path):
    binary = tmp_path / "payload.exe"
    binary.write_bytes(b"MZ\x90\x00\x03")
    with pytest.raises(UnsupportedFormatError):
        detect_format(binary, "payload.exe")


@pytest.mark.parametrize(
    ("name", "expected_hint"),
    [
        ("legacy.doc", "docx"),
        ("legacy.ppt", "pptx"),
        ("notes.rtf", "docx"),
        ("sheet.numbers", "xlsx"),
    ],
)
def test_formats_the_engine_cannot_read_fail_fast_with_a_hint(
    tmp_path, name, expected_hint
):
    """markitdown 0.1.7 has no converter for legacy binary Word/PowerPoint.

    Advertising them would mean failing after the upload; instead they are
    rejected immediately, with a message that says what to do next.
    """
    path = tmp_path / name
    path.write_bytes(_OLE2_SIGNATURE + bytes(64))
    with pytest.raises(UnsupportedFormatError) as caught:
        detect_format(path, name)
    assert expected_hint in caught.value.message


def test_supported_registry_only_advertises_what_the_engine_can_convert():
    """Every advertised format must have a converter that accepts it."""
    import io

    from markitdown import MarkItDown, StreamInfo

    from app.conversion.markitdown_adapter import MIME_BY_EXTENSION
    from app.conversion.registry import get_registry

    engine = MarkItDown(enable_builtins=True)
    # Our own converters are registered by the adapter, and OCR handles images.
    handled_elsewhere = {".json", ".xml", ".ipynb", ".png", ".jpg", ".jpeg", ".webp"}
    stream = io.BytesIO(_OLE2_SIGNATURE + bytes(512))

    unhandled = []
    for fmt in get_registry().formats:
        if fmt.extension in handled_elsewhere:
            continue
        info = StreamInfo(
            extension=fmt.extension, mimetype=MIME_BY_EXTENSION.get(fmt.extension)
        )
        accepted = False
        for registration in engine._converters:
            stream.seek(0)
            try:
                if registration.converter.accepts(stream, info):
                    accepted = True
                    break
            except Exception:
                continue
        if not accepted:
            unhandled.append(fmt.extension)

    assert not unhandled, f"advertised but no converter accepts them: {unhandled}"


def test_malformed_text_formats_are_rejected(tmp_path):
    bad_json = tmp_path / "broken.json"
    bad_json.write_text("{not valid", encoding="utf-8")
    with pytest.raises(FormatMismatchError):
        detect_format(bad_json, "broken.json")

    bad_xml = tmp_path / "broken.xml"
    bad_xml.write_text("<root><unclosed>", encoding="utf-8")
    with pytest.raises(FormatMismatchError):
        detect_format(bad_xml, "broken.xml")

    not_notebook = tmp_path / "plain.ipynb"
    not_notebook.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(FormatMismatchError):
        detect_format(not_notebook, "plain.ipynb")


def test_empty_files_are_rejected(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(CorruptFileError):
        detect_format(empty, "empty.pdf")


def test_xxe_payload_is_refused(tmp_path):
    """defusedxml must reject entity declarations rather than expanding them."""
    payload = tmp_path / "xxe.xml"
    payload.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        "<root>&xxe;</root>",
        encoding="utf-8",
    )
    with pytest.raises(ConversionError):
        detect_format(payload, "xxe.xml")


# --- archives ---------------------------------------------------------------


def _archive(tmp_path: Path, name: str, build) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        build(archive)
    return path


@pytest.mark.parametrize(
    "entry_name",
    [
        "../../evil.csv",
        "../evil.csv",
        "/etc/passwd.csv",
        "C:/Windows/evil.csv",
        "..\\..\\evil.csv",
    ],
)
def test_zip_slip_entries_are_refused(tmp_path, settings, entry_name):
    archive = _archive(
        tmp_path, "slip.zip", lambda z: z.writestr(entry_name, "a,b\n1,2\n")
    )
    with pytest.raises(ArchiveError):
        inspect_archive(archive, settings)


def test_symlink_entries_are_refused(tmp_path, settings):
    path = tmp_path / "link.zip"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("link.csv")
        info.external_attr = 0o120777 << 16  # S_IFLNK
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(ArchiveError, match="symbolic link"):
        inspect_archive(path, settings)


def test_zip_bomb_is_refused_on_uncompressed_size(tmp_path, settings):
    archive = _archive(
        tmp_path,
        "bomb.zip",
        lambda z: z.writestr("bomb.csv", "A" * (settings.max_archive_uncompressed_bytes + 1024)),
    )
    with pytest.raises(ArchiveError, match="uncompressed"):
        inspect_archive(archive, settings)


def test_too_many_entries_is_refused(tmp_path, settings):
    def build(archive):
        for index in range(settings.max_archive_files + 5):
            archive.writestr(f"file{index}.csv", "a,b\n1,2\n")

    archive = _archive(tmp_path, "many.zip", build)
    with pytest.raises(ArchiveError, match="more than"):
        inspect_archive(archive, settings)


def test_empty_archive_is_refused(tmp_path, settings):
    archive = _archive(tmp_path, "empty.zip", lambda z: None)
    with pytest.raises(ArchiveError, match="empty"):
        inspect_archive(archive, settings)


def test_nested_archives_are_not_walked(tmp_path, settings):
    archive = _archive(
        tmp_path,
        "nested.zip",
        lambda z: (
            z.writestr("inner.zip", "PK\x03\x04nested"),
            z.writestr("ok.csv", "a,b\n1,2\n"),
        ),
    )
    inspection = inspect_archive(archive, settings)
    convertible = {entry.display_name for entry in inspection.convertible}
    assert convertible == {"ok.csv"}
    assert "inner.zip" in inspection.skipped


def test_supported_entries_extract_inside_the_destination(tmp_path, settings, fixture):
    destination = tmp_path / "out"
    destination.mkdir()
    inspection = inspect_archive(fixture("bundle.zip"), settings)

    assert len(inspection.convertible) == 2
    for entry in inspection.convertible:
        extracted = extract_entry(fixture("bundle.zip"), entry, destination, settings)
        assert destination.resolve() in extracted.resolve().parents
        assert extracted.stat().st_size > 0


def test_extraction_enforces_the_byte_budget_while_streaming(tmp_path):
    """The declared size is attacker-controlled, so the cap applies to writes."""
    tight = Settings(
        workspace_root=tmp_path / "ws",
        max_file_size_mb=1,
        max_archive_uncompressed_mb=1,
        max_archive_compression_ratio=100_000,
        rate_limit_enabled=False,
    )
    payload = "x" * (2 * 1024 * 1024)
    archive = _archive(tmp_path, "big.zip", lambda z: z.writestr("big.csv", payload))

    # Inspection may already reject it; extraction must reject it regardless.
    with pytest.raises(ArchiveError):
        inspection = inspect_archive(archive, tight)
        destination = tmp_path / "dest"
        destination.mkdir()
        extract_entry(archive, inspection.entries[0], destination, tight)


# --- rate limiting ----------------------------------------------------------


def test_rate_limiter_allows_then_blocks():
    limiter = RateLimiter(enabled=True, jobs_per_hour=3, upload_mb_per_hour=100)
    key = client_key("203.0.113.5")
    for _ in range(3):
        assert limiter.check(key, 1024).allowed
    decision = limiter.check(key, 1024)
    assert not decision.allowed
    assert decision.retry_after_seconds > 0


def test_rate_limiter_caps_uploaded_bytes():
    limiter = RateLimiter(enabled=True, jobs_per_hour=100, upload_mb_per_hour=1)
    key = client_key("203.0.113.6")
    assert limiter.check(key, 900_000).allowed
    assert not limiter.check(key, 900_000).allowed


def test_clients_are_limited_independently():
    limiter = RateLimiter(enabled=True, jobs_per_hour=1, upload_mb_per_hour=100)
    assert limiter.check(client_key("198.51.100.1"), 10).allowed
    assert limiter.check(client_key("198.51.100.2"), 10).allowed


def test_client_key_does_not_reveal_the_address():
    key = client_key("203.0.113.9")
    assert "203.0.113.9" not in key
    assert key == client_key("203.0.113.9")
    assert key != client_key("203.0.113.10")


def test_disabled_limiter_always_allows():
    limiter = RateLimiter(enabled=False, jobs_per_hour=1, upload_mb_per_hour=1)
    key = client_key("203.0.113.11")
    for _ in range(50):
        assert limiter.check(key, 10_000_000).allowed
