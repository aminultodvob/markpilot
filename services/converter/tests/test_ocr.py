"""OCR pipeline tests.

These are the tests that decide whether OCR "genuinely works" rather than
merely runs. They check recognition accuracy against known fixture text,
Unicode fidelity for Bengali, structure reconstruction (headings, lists,
tables, reading order), and that preprocessing helps rather than harms.
"""

from __future__ import annotations

import re

import pytest
from PIL import Image

from app.conversion.engine import ConversionOptions
from app.conversion.errors import OcrUnavailableError
from app.ocr.layout import build_lines, reconstruct
from app.ocr.preprocess import preprocess
from app.ocr.rasterize import page_count, render_pages
from app.ocr.types import OcrWord
from tests.conftest import requires_ocr


def word_recall(markdown: str, expected: list[str]) -> float:
    """Fraction of expected words present in the output."""
    found = sum(1 for word in expected if word.lower() in markdown.lower())
    return found / len(expected)


def convert(engine, path, name, workdir, **kwargs):
    return engine.convert(
        path, filename=name, options=ConversionOptions(**kwargs), workdir=workdir
    )


# --- availability -----------------------------------------------------------


def test_ocr_provider_is_discovered(ocr_service):
    requires_ocr(ocr_service)
    assert ocr_service.provider is not None
    assert ocr_service.provider.name in ("tesseract", "vision")


def test_required_languages_are_installed(ocr_service):
    requires_ocr(ocr_service)
    languages = ocr_service.available_languages()
    assert "eng" in languages, "English language data is required"
    assert "ben" in languages, "Bengali language data is required"


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("auto", "eng+ben"), ("eng", "eng"), ("ben", "ben"), ("eng+ben", "eng+ben")],
)
def test_language_selection_resolves(ocr_service, requested, expected):
    requires_ocr(ocr_service)
    resolved, _warnings = ocr_service.resolve_languages(requested)
    assert set(resolved.split("+")) == set(expected.split("+"))


def test_unknown_language_degrades_with_a_warning(ocr_service):
    requires_ocr(ocr_service)
    resolved, warnings = ocr_service.resolve_languages("klingon")
    assert resolved  # still usable
    assert warnings and "isn't installed" in warnings[0]


# --- image OCR --------------------------------------------------------------


ENGLISH_WORDS = [
    "Annual", "Report", "2026", "Executive", "Summary",
    "financial", "performance", "Revenue", "Quarterly",
]


@pytest.mark.ocr
@pytest.mark.parametrize(
    "name", ["ocr-english.png", "ocr-english.jpg", "ocr-english.webp"]
)
def test_every_image_format_is_read(engine, fixture, workdir, ocr_service, name):
    requires_ocr(ocr_service)
    result = convert(engine, fixture(name), name, workdir)
    assert result.metadata.ocr_used is True
    assert word_recall(result.markdown, ENGLISH_WORDS) >= 0.85
    assert result.metadata.ocr_confidence is not None
    assert result.metadata.ocr_confidence > 70


@pytest.mark.ocr
def test_english_image_reconstructs_document_structure(
    engine, fixture, workdir, ocr_service
):
    requires_ocr(ocr_service)
    markdown = convert(engine, fixture("ocr-english.png"), "ocr-english.png", workdir).markdown

    # Title larger than the section headings, so it must outrank them.
    assert re.search(r"^# .*Annual Report", markdown, re.MULTILINE)
    assert re.search(r"^## .*Executive Summary", markdown, re.MULTILINE)
    assert re.search(r"^## .*Key Highlights", markdown, re.MULTILINE)

    # Bullets stay bullets and are not mistaken for headings.
    assert re.search(r"^- .*Revenue grew", markdown, re.MULTILINE)
    assert not re.search(r"^#+ - ", markdown, re.MULTILINE)

    # The quarterly figures form a real table.
    assert re.search(r"^\|.+\|[ \t]*$\n^\|[\s:|-]+\|", markdown, re.MULTILINE)
    assert "50000" in markdown and "88000" in markdown

    # Body lines are reflowed into a paragraph, not left as fragments.
    assert "summarises the financial performance of the company" in markdown


@pytest.mark.ocr
def test_table_image_becomes_a_markdown_table(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    markdown = convert(engine, fixture("ocr-table.png"), "ocr-table.png", workdir).markdown
    assert re.search(r"^\|.+\|[ \t]*$\n^\|[\s:|-]+\|", markdown, re.MULTILINE)
    for value in ("Widget", "Gadget", "Sprocket", "1200"):
        assert value in markdown


@pytest.mark.ocr
def test_multicolumn_page_keeps_reading_order(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    markdown = convert(
        engine, fixture("ocr-multicolumn.png"), "ocr-multicolumn.png", workdir
    ).markdown

    first_column = markdown.lower().find("first column begins here")
    second_column = markdown.lower().find("second column starts at the")
    assert first_column != -1 and second_column != -1
    # The whole left column must precede the right one.
    assert first_column < second_column
    assert markdown.lower().find("reading order matters") < second_column


# --- Bengali ----------------------------------------------------------------


BENGALI_WORDS = ["বার্ষিক", "প্রতিবেদন", "নির্বাহী", "সারসংক্ষেপ"]


@pytest.mark.ocr
def test_bengali_image_is_recognised(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    result = convert(engine, fixture("ocr-bengali.png"), "ocr-bengali.png", workdir)
    assert result.metadata.ocr_used is True
    assert word_recall(result.markdown, BENGALI_WORDS) >= 0.75


@pytest.mark.ocr
def test_bengali_unicode_survives_intact(engine, fixture, workdir, ocr_service):
    """No mojibake, no escapes, and the text round-trips through UTF-8."""
    requires_ocr(ocr_service)
    markdown = convert(
        engine, fixture("ocr-bengali.png"), "ocr-bengali.png", workdir
    ).markdown

    assert "�" not in markdown, "replacement characters indicate corruption"
    assert "\\u" not in markdown, "text must not be escaped"
    # Codepoints must fall in the Bengali block.
    assert any("ঀ" <= ch <= "৿" for ch in markdown)
    assert markdown.encode("utf-8").decode("utf-8") == markdown


@pytest.mark.ocr
def test_mixed_script_page_keeps_both_languages(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    markdown = convert(
        engine, fixture("ocr-mixed.png"), "ocr-mixed.png", workdir,
        ocr_languages="eng+ben",
    ).markdown

    assert re.search(r"[A-Za-z]{4,}", markdown), "Latin text missing"
    assert any("ঀ" <= ch <= "৿" for ch in markdown), "Bengali text missing"
    assert "Annual" in markdown or "Report" in markdown


# --- scanned PDFs -----------------------------------------------------------


@pytest.mark.ocr
@pytest.mark.slow
def test_scanned_pdf_triggers_ocr_automatically(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    result = convert(
        engine, fixture("scanned-english.pdf"), "scanned-english.pdf", workdir
    )
    assert result.metadata.ocr_used is True, "an image-only PDF must route to OCR"
    assert word_recall(result.markdown, ENGLISH_WORDS) >= 0.85


@pytest.mark.ocr
@pytest.mark.slow
def test_scanned_bengali_pdf_is_recognised(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    result = convert(
        engine, fixture("scanned-bengali.pdf"), "scanned-bengali.pdf", workdir
    )
    assert result.metadata.ocr_used is True
    assert word_recall(result.markdown, BENGALI_WORDS) >= 0.75


@pytest.mark.ocr
@pytest.mark.slow
def test_multipage_scan_converts_every_page(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    result = convert(
        engine, fixture("scanned-multipage.pdf"), "scanned-multipage.pdf", workdir
    )
    assert result.metadata.ocr_pages == 2
    # Page one content and page two content must both be present.
    assert "Annual Report" in result.markdown
    assert "Inventory Report" in result.markdown or "Widget" in result.markdown


@pytest.mark.ocr
def test_orientation_off_still_reads_an_upright_scan(fixture, workdir, settings):
    """The free-tier speed path: skipping the orientation pass must not hurt
    accuracy on upright documents (scanned PDFs, screenshots)."""
    from dataclasses import replace as _replace  # noqa: F401

    from app.config import Settings
    from app.conversion.engine import ConversionEngine
    from app.ocr.service import OcrService

    fast = Settings(
        workspace_root=settings.workspace_root,
        rate_limit_enabled=False,
        ocr_detect_orientation=False,
        tesseract_cmd=settings.tesseract_cmd,
        tessdata_prefix=settings.tessdata_prefix,
    )
    requires_ocr(OcrService(fast))
    result = ConversionEngine(fast).convert(
        fixture("ocr-english.png"),
        filename="ocr-english.png",
        options=ConversionOptions(),
        workdir=workdir,
    )
    assert result.metadata.ocr_used is True
    assert word_recall(result.markdown, ENGLISH_WORDS) >= 0.85


def test_text_pdf_never_invokes_ocr(engine, fixture, workdir):
    """Running OCR on a real text layer would be slower and less accurate."""
    result = convert(engine, fixture("text.pdf"), "text.pdf", workdir)
    assert result.metadata.ocr_used is False
    assert result.metadata.ocr_confidence is None


@pytest.mark.ocr
@pytest.mark.slow
def test_forcing_ocr_overrides_the_text_layer(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    result = convert(engine, fixture("text.pdf"), "text.pdf", workdir, ocr_mode="force")
    assert result.metadata.ocr_used is True


def test_ocr_off_rejects_an_image(engine, fixture, workdir):
    with pytest.raises(OcrUnavailableError):
        convert(engine, fixture("ocr-english.png"), "x.png", workdir, ocr_mode="off")


# --- difficult scans --------------------------------------------------------


@pytest.mark.ocr
def test_skewed_page_is_straightened(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    result = convert(engine, fixture("ocr-skewed.png"), "ocr-skewed.png", workdir)
    assert word_recall(result.markdown, ENGLISH_WORDS) >= 0.7


@pytest.mark.ocr
def test_low_quality_scan_still_yields_text(engine, fixture, workdir, ocr_service):
    requires_ocr(ocr_service)
    result = convert(
        engine, fixture("ocr-low-quality.png"), "ocr-low-quality.png", workdir
    )
    assert word_recall(result.markdown, ["Faded", "Receipt", "1450"]) >= 0.6


@pytest.mark.ocr
def test_preprocessing_never_degrades_a_clean_page(fixture, ocr_service):
    """The regression that motivated measuring before enhancing."""
    requires_ocr(ocr_service)
    provider = ocr_service.provider

    with Image.open(fixture("ocr-english.png")) as image:
        original = image.convert("L")
        prepared, report = preprocess(image.copy())

    raw_words = provider.extract_words(original, languages="eng")
    prepared_words = provider.extract_words(prepared, languages="eng")

    raw_confidence = sum(w.confidence for w in raw_words) / max(len(raw_words), 1)
    prepared_confidence = sum(w.confidence for w in prepared_words) / max(
        len(prepared_words), 1
    )

    assert prepared_confidence >= raw_confidence - 2.0, (
        f"preprocessing hurt a clean page: {raw_confidence:.1f} -> "
        f"{prepared_confidence:.1f} (steps: {report.steps})"
    )


def test_clean_page_needs_no_enhancement(fixture):
    """A crisp page should pass through untouched."""
    with Image.open(fixture("ocr-english.png")) as image:
        _prepared, report = preprocess(image.copy())
    assert not report.contrast_enhanced
    assert not report.denoised


# --- rasterization ----------------------------------------------------------


def test_page_count_and_rendering(fixture):
    path = fixture("scanned-multipage.pdf")
    assert page_count(path) == 2

    rendered = list(render_pages(path, dpi=150, max_pages=5))
    assert [number for number, _ in rendered] == [1, 2]
    assert all(image.width > 500 for _, image in rendered)


def test_render_respects_the_page_limit(fixture):
    rendered = list(render_pages(fixture("scanned-multipage.pdf"), dpi=100, max_pages=1))
    assert len(rendered) == 1


def test_render_honours_an_explicit_page_list(fixture):
    rendered = list(
        render_pages(fixture("scanned-multipage.pdf"), dpi=100, pages=[2])
    )
    assert [number for number, _ in rendered] == [2]


# --- layout reconstruction (no OCR engine needed) ---------------------------


def _word(text, left, top, width, height, line, *, block=1, paragraph=1):
    return OcrWord(
        text=text, left=left, top=top, width=width, height=height,
        confidence=95.0, block=block, paragraph=paragraph, line=line,
    )


def test_layout_promotes_a_larger_line_to_a_heading():
    words = [
        _word("Title", 100, 100, 300, 60, line=1),
        *[
            _word(w, 100 + i * 90, 220, 80, 26, line=2)
            for i, w in enumerate(["body", "text", "here", "and", "more", "words"])
        ],
    ]
    markdown, _ = reconstruct(words, page_width=1700)
    assert markdown.startswith("#")
    assert "Title" in markdown


def test_layout_detects_bullets_before_headings():
    words = [
        _word("-", 100, 100, 20, 30, line=1),
        _word("item", 140, 100, 120, 30, line=1),
    ]
    markdown, _ = reconstruct(words, page_width=1700)
    assert markdown.startswith("- item")


def test_layout_returns_a_warning_for_an_empty_page():
    markdown, warnings = reconstruct([], page_width=1700)
    assert markdown == ""
    assert warnings == []


def test_build_lines_groups_by_tesseract_line_numbers():
    words = [
        _word("a", 100, 100, 40, 26, line=1),
        _word("b", 150, 100, 40, 26, line=1),
        _word("c", 100, 140, 40, 26, line=2),
    ]
    lines = build_lines(words)
    assert [line.text for line in lines] == ["a b", "c"]
