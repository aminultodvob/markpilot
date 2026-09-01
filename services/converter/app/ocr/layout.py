"""Reconstructing document structure from positioned OCR words.

Raw OCR gives one string per visual line. Emitting those directly produces the
familiar unusable output::

    Annual
    Report
    2026
    Executive
    Summary

What we want instead is::

    # Annual Report 2026

    ## Executive Summary

Getting there means using the *geometry* Tesseract returns alongside the text.
This module infers, in order:

* **reading order** - detecting a two-column layout from a vertical whitespace
  gutter, and splitting the page into bands around full-width lines so a
  spanning title is not shuffled into a column;
* **tables** - runs of lines whose words cluster into the same x positions,
  separated by gaps far wider than a normal word space;
* **headings** - lines noticeably taller than the document's body text;
* **lists** - lines opening with a bullet or an enumerator, including Bengali
  digits;
* **paragraphs** - lines reflowed into prose, rejoining hyphenated breaks.

Every rule is a heuristic over measurements, never over language, so it behaves
the same for English and Bengali.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median

from app.conversion.normalize import join_ocr_lines
from app.ocr.types import OcrLine, OcrWord

# --- tuning -----------------------------------------------------------------
# A line this much taller than body text is a heading.
HEADING_RATIO_H1 = 1.70
HEADING_RATIO_H2 = 1.40
HEADING_RATIO_H3 = 1.22
MAX_HEADING_WORDS = 14
# Word gap this many times the typical character width starts a new table cell.
CELL_GAP_FACTOR = 2.6
MIN_TABLE_ROWS = 2
MAX_TABLE_COLUMNS = 10
# Gutter must be at least this fraction of the page to imply two columns.
MIN_GUTTER_FRACTION = 0.035
# If more than this fraction of lines cross the gutter, it is not a gutter.
MAX_GUTTER_CROSSERS = 0.12
# A line covering this much of the content width spans the page.
FULL_WIDTH_FRACTION = 0.62

_BULLET = re.compile(r"^\s*([•▪●○◦⁃–—*+-])\s+")
# Latin and Bengali enumerators: "1." "2)" "(3)" "a." and "১." "২)".
_ENUMERATOR = re.compile(r"^\s*\(?([0-9০-৯]{1,3}|[a-zA-Z])[.)]\s+")
_HAS_CASE = re.compile(r"[a-zA-Z]")


@dataclass
class _Band:
    """A horizontal slice of the page, laid out independently."""

    lines: list[OcrLine]
    full_width: OcrLine | None = None


def build_lines(words: list[OcrWord]) -> list[OcrLine]:
    """Group words into visual lines using Tesseract's own line numbering."""
    grouped: dict[tuple[int, int, int], list[OcrWord]] = {}
    for word in words:
        grouped.setdefault((word.block, word.paragraph, word.line), []).append(word)

    lines = []
    for key in sorted(grouped):
        line_words = sorted(grouped[key], key=lambda w: w.left)
        if line_words:
            lines.append(OcrLine(words=line_words))
    return lines


def body_text_height(lines: list[OcrLine]) -> float:
    """The document's body text size.

    Weighted by word count so body text, which has many words per line, sets
    the baseline rather than headings, which have few. A plain median over
    lines is easily skewed on a page that is mostly headings.
    """
    heights: list[float] = []
    for line in lines:
        if line.words:
            heights.extend([line.normalized_height] * len(line.words))
    return median(heights) if heights else 0.0


def _typical_char_width(lines: list[OcrLine]) -> float:
    widths = [
        w.width / len(w.text)
        for line in lines
        for w in line.words
        if w.text and len(w.text) > 1
    ]
    return median(widths) if widths else 8.0


# --- reading order ----------------------------------------------------------


def _find_gutter(lines: list[OcrLine], page_width: int) -> tuple[int, int] | None:
    """Locate a vertical whitespace band splitting the page into two columns."""
    if len(lines) < 6 or page_width <= 0:
        return None

    covered = [False] * page_width
    for line in lines:
        left = max(0, min(line.left, page_width - 1))
        right = max(0, min(line.right, page_width - 1))
        for x in range(left, right + 1):
            covered[x] = True

    # Only look for a gutter near the middle; margins are whitespace too.
    search_start, search_end = int(page_width * 0.25), int(page_width * 0.75)
    best: tuple[int, int] | None = None
    run_start: int | None = None

    for x in range(search_start, search_end):
        if not covered[x]:
            if run_start is None:
                run_start = x
        else:
            if run_start is not None:
                if best is None or (x - run_start) > (best[1] - best[0]):
                    best = (run_start, x)
                run_start = None
    if run_start is not None and (
        best is None or (search_end - run_start) > (best[1] - best[0])
    ):
        best = (run_start, search_end)

    if best is None or (best[1] - best[0]) < page_width * MIN_GUTTER_FRACTION:
        return None

    crossers = sum(1 for ln in lines if ln.left < best[0] and ln.right > best[1])
    if crossers > len(lines) * MAX_GUTTER_CROSSERS:
        return None
    return best


def _order_lines(lines: list[OcrLine], page_width: int) -> list[OcrLine]:
    """Return lines in human reading order, handling two-column layouts."""
    if not lines:
        return []

    gutter = _find_gutter(lines, page_width)
    if gutter is None:
        return sorted(lines, key=lambda ln: (ln.top, ln.left))

    gutter_start, gutter_end = gutter
    content_left = min(ln.left for ln in lines)
    content_right = max(ln.right for ln in lines)
    content_width = max(content_right - content_left, 1)

    # Split into bands at every full-width line so spanning titles stay put.
    bands: list[_Band] = [_Band(lines=[])]
    for line in sorted(lines, key=lambda ln: (ln.top, ln.left)):
        spans = (
            line.left < gutter_start
            and line.right > gutter_end
            and (line.right - line.left) > content_width * FULL_WIDTH_FRACTION
        )
        if spans:
            bands[-1].full_width = line
            bands.append(_Band(lines=[]))
        else:
            bands[-1].lines.append(line)

    ordered: list[OcrLine] = []
    for band in bands:
        left_col = [ln for ln in band.lines if ln.center_x <= gutter_start]
        right_col = [ln for ln in band.lines if ln.center_x > gutter_start]
        ordered.extend(sorted(left_col, key=lambda ln: (ln.top, ln.left)))
        ordered.extend(sorted(right_col, key=lambda ln: (ln.top, ln.left)))
        if band.full_width is not None:
            ordered.append(band.full_width)
    return ordered


# --- tables -----------------------------------------------------------------


def _line_cells(line: OcrLine, gap_threshold: float) -> list[tuple[int, str]]:
    """Split a line into (x position, text) cells at unusually wide gaps."""
    cells: list[tuple[int, str]] = []
    current: list[OcrWord] = []
    for word in line.words:
        if current and (word.left - current[-1].right) > gap_threshold:
            cells.append((current[0].left, " ".join(w.text for w in current)))
            current = []
        current.append(word)
    if current:
        cells.append((current[0].left, " ".join(w.text for w in current)))
    return cells


def _detect_table_runs(
    lines: list[OcrLine], gap_threshold: float
) -> dict[int, tuple[int, list[list[tuple[int, str]]]]]:
    """Map a start index to (length, rows) for each detected table run."""
    cells_per_line = [_line_cells(line, gap_threshold) for line in lines]
    runs: dict[int, tuple[int, list[list[tuple[int, str]]]]] = {}

    index = 0
    while index < len(lines):
        if len(cells_per_line[index]) < 2:
            index += 1
            continue
        end = index
        column_count = len(cells_per_line[index])
        while (
            end + 1 < len(lines)
            and len(cells_per_line[end + 1]) >= 2
            # Allow a one-cell difference for merged or empty cells.
            and abs(len(cells_per_line[end + 1]) - column_count) <= 1
        ):
            end += 1
        if end - index + 1 >= MIN_TABLE_ROWS:
            runs[index] = (end - index + 1, cells_per_line[index : end + 1])
            index = end + 1
        else:
            index += 1
    return runs


def _render_table(rows: list[list[tuple[int, str]]]) -> str | None:
    """Align cell runs onto shared columns and render a Markdown table."""
    positions = sorted({x for row in rows for x, _ in row})
    if not positions:
        return None

    # Cluster x positions that are close enough to be the same column.
    spread = max(positions) - min(positions)
    tolerance = max(spread * 0.06, 12.0)
    columns: list[float] = []
    for x in positions:
        if not columns or x - columns[-1] > tolerance:
            columns.append(float(x))
    if len(columns) < 2 or len(columns) > MAX_TABLE_COLUMNS:
        return None

    table: list[list[str]] = []
    for row in rows:
        cells = [""] * len(columns)
        for x, text in row:
            index = min(
                range(len(columns)), key=lambda i: abs(columns[i] - x)
            )
            cells[index] = (cells[index] + " " + text).strip()
        table.append([c.replace("|", "\\|") for c in cells])

    if not any(any(c for c in row) for row in table):
        return None

    header, *body = table
    if not any(header):
        return None
    rendered = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    rendered.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(rendered)


# --- classification ---------------------------------------------------------


def _heading_level(line: OcrLine, body_height: float) -> int | None:
    if body_height <= 0 or not line.words:
        return None
    if len(line.words) > MAX_HEADING_WORDS:
        return None

    ratio = line.normalized_height / body_height
    if ratio >= HEADING_RATIO_H1:
        return 1
    if ratio >= HEADING_RATIO_H2:
        return 2
    if ratio >= HEADING_RATIO_H3:
        return 3

    # All-caps short lines read as headings, but only in cased scripts, so this
    # never misfires on Bengali.
    text = line.text.strip()
    if (
        len(line.words) <= 8
        and _HAS_CASE.search(text)
        and text == text.upper()
        and len(text) >= 3
    ):
        return 2
    return None


def _median_word_width(lines: list[OcrLine]) -> float:
    widths = [w.width for line in lines for w in line.words]
    return median(widths) if widths else 0.0


def _wrap_thresholds(
    lines: list[OcrLine], gap_threshold: float
) -> dict[int, float]:
    """Per-block x position past which a line counts as having wrapped.

    A paragraph's interior lines run to the right margin; only its final line
    stops short. Knowing where the margin sits therefore tells us where
    paragraphs end - far more reliably than Tesseract's own paragraph
    numbering, which splits mid-sentence on many real scans.

    The margin is computed per text block rather than per page, because table
    rows and a second column reach further right than body prose and would
    otherwise drag the threshold past every real line.
    """
    # Ragged-right text stops short of the margin by however long the next word
    # was, so the allowance has to be about a word wide, not a space wide.
    allowance = max(gap_threshold, _median_word_width(lines) * 1.3)

    by_block: dict[int, list[int]] = {}
    for line in lines:
        by_block.setdefault(line.block, []).append(line.right)

    thresholds: dict[int, float] = {}
    for block, rights in by_block.items():
        rights.sort()
        # 90th percentile ignores an odd over-wide line without chasing outliers.
        margin = rights[int(len(rights) * 0.9)] if len(rights) > 1 else rights[0]
        thresholds[block] = margin - allowance
    return thresholds


def _continues_paragraph(
    previous: OcrLine | None,
    current: OcrLine,
    body_height: float,
    wrap_thresholds: dict[int, float],
) -> bool:
    """Whether ``current`` is a continuation of the paragraph ``previous`` began."""
    if previous is None:
        return True
    if current.block != previous.block:
        return False
    # A gap much larger than normal leading means a new block of text.
    vertical_gap = current.top - previous.bottom
    if body_height > 0 and vertical_gap > body_height * 1.2:
        return False
    # If the previous line stopped short of the margin, the paragraph ended.
    threshold = wrap_thresholds.get(previous.block)
    return threshold is None or previous.right >= threshold


def _list_marker(text: str) -> tuple[str, str] | None:
    """Return (marker, remaining text) when the line opens a list item."""
    bullet = _BULLET.match(text)
    if bullet:
        return "-", text[bullet.end() :].strip()
    enumerator = _ENUMERATOR.match(text)
    if enumerator:
        return f"{enumerator.group(1)}.", text[enumerator.end() :].strip()
    return None


# --- assembly ---------------------------------------------------------------


def reconstruct(
    words: list[OcrWord],
    *,
    page_width: int,
    body_height: float | None = None,
) -> tuple[str, list[str]]:
    """Turn positioned words into structured Markdown.

    ``body_height`` may be supplied by the caller so heading levels stay
    consistent across every page of a document rather than being recomputed
    per page.
    """
    lines = build_lines(words)
    if not lines:
        return "", []

    warnings: list[str] = []
    ordered = _order_lines(lines, page_width)
    height = body_height or body_text_height(lines)
    gap_threshold = _typical_char_width(lines) * CELL_GAP_FACTOR
    table_runs = _detect_table_runs(ordered, gap_threshold)

    # Margins are measured from body prose only: table rows run wider, and
    # headings sit on their own, so including either moves the margin past
    # every genuine wrapped line.
    table_line_indices = {
        i for start, (length, _) in table_runs.items() for i in range(start, start + length)
    }
    body_candidates = [
        line
        for i, line in enumerate(ordered)
        if i not in table_line_indices and _heading_level(line, height) is None
    ]
    wrap_thresholds = _wrap_thresholds(body_candidates or ordered, gap_threshold)

    blocks: list[str] = []
    paragraph_buffer: list[str] = []
    previous_line: OcrLine | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph_buffer
        if paragraph_buffer:
            text = join_ocr_lines(paragraph_buffer)
            if text:
                blocks.append(text)
        paragraph_buffer = []

    index = 0
    while index < len(ordered):
        if index in table_runs:
            length, rows = table_runs[index]
            rendered = _render_table(rows)
            if rendered:
                flush_paragraph()
                blocks.append(rendered)
                index += length
                continue

        line = ordered[index]
        text = line.text.strip()
        if not text:
            index += 1
            continue

        # List markers are checked first: a bullet line carrying a descender
        # can measure tall enough to trip the heading test, and "### - item"
        # is always wrong.
        marker = _list_marker(text)
        if marker is not None:
            flush_paragraph()
            blocks.append(f"{marker[0]} {marker[1]}")
            index += 1
            continue

        level = _heading_level(line, height)
        if level is not None:
            flush_paragraph()
            blocks.append(f"{'#' * level} {text}")
            index += 1
            continue

        if paragraph_buffer and not _continues_paragraph(
            previous_line, line, height, wrap_thresholds
        ):
            flush_paragraph()
        paragraph_buffer.append(text)
        previous_line = line
        index += 1

    flush_paragraph()

    if not blocks:
        warnings.append("No readable text was found on this page.")

    return "\n\n".join(blocks).strip(), warnings
