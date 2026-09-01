"""Markdown post-processing.

Scope is deliberately narrow. This layer tidies *formatting* - line endings,
blank-line runs, heading spacing, stray control characters - and never rewrites
the author's words. A converter must be faithful: if the source said something,
the output says the same thing.

Raw HTML that survives conversion is *reported*, not stripped, so the
downloaded Markdown stays true to the source. Rendering safety is handled where
it belongs: the preview sanitizes HTML before it reaches the DOM.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

# Control characters that have no business in text, keeping \n and \t.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")
_ATX_HEADING = re.compile(r"^(#{1,6})[ \t]*(\S.*?)[ \t]*#*$", re.MULTILINE)
_HEADING_LINE = re.compile(r"^#{1,6} ")
_FENCE = re.compile(r"^(```|~~~)")

# Patterns that indicate executable or embedding HTML survived conversion.
_RISKY_HTML = re.compile(
    r"<\s*(script|iframe|object|embed|svg|form|link|meta|base)\b"
    r"|\son[a-z]+\s*="
    r"|javascript\s*:",
    re.IGNORECASE,
)


def contains_raw_html(markdown: str) -> bool:
    """True when the Markdown carries HTML that a renderer must sanitize."""
    return bool(_RISKY_HTML.search(markdown))


def _split_fenced(markdown: str) -> list[tuple[bool, str]]:
    """Split into (is_code_fence, text) segments so code is left untouched."""
    segments: list[tuple[bool, str]] = []
    buffer: list[str] = []
    in_fence = False
    fence_marker = ""

    for line in markdown.split("\n"):
        match = _FENCE.match(line.strip())
        if match and not in_fence:
            segments.append((False, "\n".join(buffer)))
            buffer = [line]
            in_fence = True
            fence_marker = match.group(1)
        elif in_fence and line.strip().startswith(fence_marker):
            buffer.append(line)
            segments.append((True, "\n".join(buffer)))
            buffer = []
            in_fence = False
        else:
            buffer.append(line)

    if buffer:
        segments.append((in_fence, "\n".join(buffer)))
    return segments


def _outside_fences(text: str, transform: Callable[[str], str]) -> str:
    """Apply ``transform`` to prose segments only, leaving code fences intact."""
    return "\n".join(
        segment if is_code else transform(segment)
        for is_code, segment in _split_fenced(text)
    )


def _space_headings(text: str) -> str:
    """Guarantee one blank line above and below each ATX heading."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        is_heading = bool(_HEADING_LINE.match(line))
        if is_heading and out and out[-1].strip():
            out.append("")
        out.append(line)
        if is_heading:
            out.append("")
    # Drop the duplicate blank a heading may have introduced.
    cleaned: list[str] = []
    for line in out:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def normalize_markdown(markdown: str) -> str:
    """Tidy Markdown formatting without altering its meaning."""
    if not markdown:
        return ""

    # Normalise line endings and Unicode form first so later regexes are stable.
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace("﻿", "")
    text = _CONTROL.sub("", text)

    def tidy(segment: str) -> str:
        part = _TRAILING_WS.sub("", segment)
        # "#Title" and "## Title ##" both become "## Title".
        part = _ATX_HEADING.sub(lambda m: f"{m.group(1)} {m.group(2)}", part)
        part = _space_headings(part)
        return _BLANK_RUN.sub("\n\n", part)

    text = _outside_fences(text, tidy)
    # Joining segments can reintroduce a blank run at the seams. This pass is
    # also fence-aware: blank lines inside a code block are part of the code
    # and collapsing them would corrupt the snippet.
    text = _outside_fences(text, lambda s: _BLANK_RUN.sub("\n\n", s))
    return text.strip("\n") + "\n" if text.strip() else ""


def join_ocr_lines(lines: list[str]) -> str:
    """Reflow OCR line fragments into a paragraph.

    OCR emits one string per visual line, so a sentence arrives pre-broken.
    Hyphenated splits are rejoined; every other break becomes a space.
    """
    if not lines:
        return ""
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not out:
            out = line
        elif out.endswith("-") and not out.endswith("--"):
            # "inter-\nnational" is one word, so drop the hyphen.
            out = out[:-1] + line
        else:
            out = f"{out} {line}"
    return out


def estimate_reading_stats(markdown: str) -> tuple[int, int]:
    """Return (word_count, character_count) for result metadata."""
    return len(markdown.split()), len(markdown)
