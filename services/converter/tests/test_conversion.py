"""Conversion quality tests.

These assert on the *content* of the Markdown, not merely that conversion
succeeded. A converter that returns a 200 and a page of garbage has failed, so
every format is checked for the structure it is supposed to preserve:
headings, tables, list items, code fences, sheet names, slide titles, and
Unicode fidelity.
"""

from __future__ import annotations

import re

import pytest

from app.conversion.engine import ConversionOptions, parse_page_range
from app.conversion.errors import ConversionError
from app.conversion.normalize import (
    contains_raw_html,
    join_ocr_lines,
    normalize_markdown,
)
from app.conversion.registry import get_registry


def convert(engine, fixture, name, workdir, **kwargs):
    options = ConversionOptions(**kwargs)
    return engine.convert(
        fixture(name), filename=name, options=options, workdir=workdir
    )


def has_table(markdown: str) -> bool:
    """A Markdown table needs a header row followed by a delimiter row."""
    return bool(
        re.search(r"^\|.+\|[ \t]*$\n^\|[\s:|-]+\|[ \t]*$", markdown, re.MULTILINE)
    )


# --- registry ---------------------------------------------------------------


def test_registry_covers_every_required_format():
    registry = get_registry()
    required = {
        ".pdf", ".docx", ".pptx", ".xls", ".xlsx",
        ".html", ".csv", ".json", ".xml", ".ipynb", ".epub", ".zip",
        ".png", ".jpg", ".jpeg", ".webp",
    }
    assert required <= registry.extensions


def test_registry_does_not_advertise_unconvertible_legacy_formats():
    """markitdown 0.1.7 has no converter for legacy binary Word/PowerPoint.

    Listing them would mean accepting an upload we cannot convert. Legacy
    .xls *is* supported (XlsConverter), so it stays.
    """
    extensions = get_registry().extensions
    assert ".doc" not in extensions
    assert ".ppt" not in extensions
    assert ".xls" in extensions


def test_every_format_belongs_to_a_declared_category():
    registry = get_registry()
    categories = {category.id for category in registry.categories}
    assert all(fmt.category in categories for fmt in registry.formats)


# --- normalization ----------------------------------------------------------


def test_blank_line_runs_collapse():
    assert normalize_markdown("a\n\n\n\n\nb") == "a\n\nb\n"


def test_headings_get_breathing_room_and_a_space_after_the_hashes():
    result = normalize_markdown("text\n#Title\nmore")
    assert "\n# Title\n" in result
    assert "text\n\n# Title\n\nmore" in result


def test_closing_hashes_are_stripped():
    assert normalize_markdown("## Title ##").strip() == "## Title"


def test_line_endings_are_normalized():
    assert "\r" not in normalize_markdown("a\r\nb\r\nc")


def test_code_fences_are_left_alone():
    source = "```python\ndef f():\n\n\n    return 1\n```\n"
    result = normalize_markdown(source)
    # The blank run inside the fence must survive; it is part of the code.
    assert "def f():\n\n\n    return 1" in result


def test_normalization_does_not_rewrite_wording():
    source = "The quick brown fox jumps over the lazy dog."
    assert source in normalize_markdown(source)


def test_raw_html_is_detected_but_preserved():
    source = "# Title\n\n<script>alert(1)</script>\n"
    result = normalize_markdown(source)
    assert contains_raw_html(result)
    # Faithfulness: the downloaded Markdown still reflects the source. Safety
    # is applied when rendering, not by silently editing the document.
    assert "<script>" in result


def test_ocr_line_joining_repairs_hyphenation():
    assert join_ocr_lines(["inter-", "national"]) == "international"
    assert join_ocr_lines(["one", "two", "three"]) == "one two three"
    assert join_ocr_lines([]) == ""


# --- page ranges ------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (None, None),
        ("", None),
        ("1", [1]),
        ("1-3", [1, 2, 3]),
        ("1-3,7", [1, 2, 3, 7]),
        ("5,1-2", [1, 2, 5]),
        ("2-2", [2]),
    ],
)
def test_page_range_parsing(spec, expected):
    assert parse_page_range(spec) == expected


@pytest.mark.parametrize("spec", ["0", "abc", "3-1", "-5", "1-999999"])
def test_invalid_page_ranges_are_rejected(spec):
    with pytest.raises(ValueError):
        parse_page_range(spec)


# --- per-format quality -----------------------------------------------------


def test_text_pdf_is_read_without_ocr(engine, fixture, workdir):
    result = convert(engine, fixture, "text.pdf", workdir)
    assert result.metadata.ocr_used is False
    assert result.metadata.pages == 2
    assert "Quarterly Update" in result.markdown
    assert "real text layer" in result.markdown
    # Both pages must be present.
    assert "Page Two" in result.markdown


def test_pdf_page_range_limits_the_output(engine, fixture, workdir):
    result = convert(engine, fixture, "text.pdf", workdir, page_range="2")
    assert "Page Two" in result.markdown
    assert "Quarterly Update" not in result.markdown
    assert result.metadata.pages == 1


def test_docx_preserves_headings_lists_and_tables(engine, fixture, workdir):
    result = convert(engine, fixture, "proposal.docx", workdir)
    markdown = result.markdown
    assert re.search(r"^#+ Project Proposal", markdown, re.MULTILINE)
    assert re.search(r"^#+ Objectives", markdown, re.MULTILINE)
    assert "Reduce processing time" in markdown
    assert has_table(markdown)
    assert "Engineering" in markdown and "120000" in markdown


def test_pptx_preserves_slide_titles_bullets_and_notes(engine, fixture, workdir):
    markdown = convert(engine, fixture, "deck.pptx", workdir).markdown
    assert "Market Overview" in markdown
    assert "Key Findings" in markdown
    assert "Demand increased in every region" in markdown
    assert "supply chain recovery" in markdown  # speaker notes


def test_xlsx_emits_one_table_per_worksheet(engine, fixture, workdir):
    markdown = convert(engine, fixture, "workbook.xlsx", workdir).markdown
    assert "Sales" in markdown and "Expenses" in markdown
    assert markdown.count("| --- |") >= 2 or markdown.count("---") >= 2
    assert has_table(markdown)
    assert "Product A" in markdown and "Marketing" in markdown


def test_csv_becomes_a_markdown_table(engine, fixture, workdir):
    markdown = convert(engine, fixture, "table.csv", workdir).markdown
    assert has_table(markdown)
    assert "Alpha" in markdown and "50000" in markdown


def test_json_is_structured_rather_than_dumped(engine, fixture, workdir):
    markdown = convert(engine, fixture, "records.json", workdir).markdown
    # The title is promoted to a heading, and the uniform list becomes a table.
    assert re.search(r"^# Quarterly Report", markdown, re.MULTILINE)
    assert has_table(markdown)
    assert "alpha" in markdown and "beta" in markdown
    # It must not simply echo the raw source back.
    assert '"items":' not in markdown


def test_xml_preserves_hierarchy_and_attributes(engine, fixture, workdir):
    markdown = convert(engine, fixture, "catalog.xml", workdir).markdown
    assert re.search(r"^# Catalog", markdown, re.MULTILINE)
    assert "Acme" in markdown  # vendor attribute
    assert has_table(markdown)  # repeated <book> siblings
    assert "Deep Work" in markdown and "Wide Nets" in markdown
    assert "<book" not in markdown  # no raw markup leaked


def test_html_becomes_clean_markdown(engine, fixture, workdir):
    markdown = convert(engine, fixture, "page.html", workdir).markdown
    assert re.search(r"^#+ Sample Page", markdown, re.MULTILINE)
    assert "**bold**" in markdown or "bold" in markdown
    assert "First item" in markdown
    assert "https://example.com" in markdown


def test_ipynb_keeps_code_and_outputs(engine, fixture, workdir):
    markdown = convert(engine, fixture, "notebook.ipynb", workdir).markdown
    assert "# Analysis" in markdown
    assert "```python" in markdown
    assert "print(6 * 7)" in markdown
    # MarkItDown drops outputs; our converter keeps them.
    assert "42" in markdown


def test_epub_extracts_chapters(engine, fixture, workdir):
    markdown = convert(engine, fixture, "book.epub", workdir).markdown
    assert "The Beginning" in markdown
    assert "The Middle" in markdown
    assert "opening chapter" in markdown


def test_archive_is_reported_for_expansion(engine, fixture, workdir):
    from app.conversion.engine import ArchiveMarker

    outcome = engine.convert(
        fixture("bundle.zip"), filename="bundle.zip", workdir=workdir
    )
    assert isinstance(outcome, ArchiveMarker)


def test_metadata_is_populated_and_leaks_no_paths(engine, fixture, workdir):
    result = convert(engine, fixture, "workbook.xlsx", workdir)
    data = result.metadata.to_dict()

    assert data["format"] == "xlsx"
    assert data["word_count"] > 0
    assert data["character_count"] > 0
    assert data["source_bytes"] > 0
    assert data["duration_ms"] >= 0
    assert "markitdown" in data["engine"]

    serialized = str(data)
    for leak in ("/tmp", "C:\\", "workspace", "uploads"):
        assert leak not in serialized


def test_corrupt_document_raises_a_clean_error(engine, tmp_path, workdir):
    broken = tmp_path / "broken.docx"
    # Valid ZIP signature and a docx marker, but structurally nonsense.
    import zipfile

    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("word/document.xml", "not really xml <<<")

    with pytest.raises(ConversionError) as caught:
        engine.convert(broken, filename="broken.docx", workdir=workdir)
    # A user-facing sentence, never a traceback.
    assert caught.value.message
    assert "Traceback" not in caught.value.message


def test_oversized_output_is_truncated_with_a_warning(tmp_path, workdir):
    """A modest spreadsheet can expand into millions of words.

    The upload limit does not bound this, and results are held in memory, so
    the output itself is capped - and the user is told, never silently cut.
    """
    import openpyxl

    from app.config import Settings
    from app.conversion.engine import ConversionEngine

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append([f"col{c}" for c in range(20)])
    for row in range(4000):
        sheet.append([f"r{row}c{c}" for c in range(20)])
    source = tmp_path / "big.xlsx"
    workbook.save(source)

    limit = 120_000
    settings = Settings(
        workspace_root=tmp_path / "ws",
        max_output_characters=limit,
        rate_limit_enabled=False,
    )
    result = ConversionEngine(settings).convert(
        source, filename="big.xlsx", options=ConversionOptions(), workdir=workdir
    )

    assert len(result.markdown) <= limit + 200, "output must respect the cap"
    assert "Output truncated" in result.markdown
    assert any("truncated" in w.lower() for w in result.warnings)


def test_normal_output_is_never_truncated(engine, fixture, workdir):
    result = convert(engine, fixture, "workbook.xlsx", workdir)
    assert "Output truncated" not in result.markdown
    assert not any("truncated" in w.lower() for w in result.warnings)
