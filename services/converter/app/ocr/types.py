"""Data structures shared across the OCR pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

# Latin glyphs that reach below the baseline / above the x-height. Used to work
# out how much vertical room a line's text was entitled to occupy.
_DESCENDERS = frozenset("gjpqy")
_ASCENDERS = frozenset("bdfhklt")
# Ratios of actual ink extent to full ascender-to-descender extent.
_FACTOR_TALL_ONLY = 0.78
_FACTOR_DESCENDER_ONLY = 0.82
_FACTOR_X_HEIGHT_ONLY = 0.58


def _extent_factor(text: str) -> float:
    """Fraction of the full font extent that ``text`` can actually occupy.

    Returns 1.0 for non-Latin scripts (Bengali, for one, has no case and sets
    consistently against its matra line), so normalisation never distorts them.
    """
    if not any(c.isascii() and c.isalpha() for c in text):
        return 1.0
    has_descender = any(c in _DESCENDERS for c in text)
    has_tall = any(c.isupper() or c in _ASCENDERS or c.isdigit() for c in text)
    if has_descender and has_tall:
        return 1.0
    if has_tall:
        return _FACTOR_TALL_ONLY
    if has_descender:
        return _FACTOR_DESCENDER_ONLY
    return _FACTOR_X_HEIGHT_ONLY


@dataclass(frozen=True)
class OcrWord:
    """One recognised word with its position on the page."""

    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float
    block: int
    paragraph: int
    line: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2


@dataclass
class OcrLine:
    """A visual line of text, assembled from words."""

    words: list[OcrWord]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def left(self) -> int:
        return min(w.left for w in self.words)

    @property
    def right(self) -> int:
        return max(w.right for w in self.words)

    @property
    def top(self) -> int:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> int:
        return max(w.bottom for w in self.words)

    @property
    def height(self) -> float:
        return median([w.height for w in self.words])

    @property
    def span(self) -> int:
        """Full ink extent of the line, top of ascenders to bottom of descenders.

        More stable than the median word height: every word in a line shares
        one baseline and font size, so the union bounding box is set by the
        font rather than by which glyphs a particular word happened to use.
        """
        return self.bottom - self.top

    @property
    def normalized_height(self) -> float:
        """Line span corrected for which glyph classes the text contains.

        Two lines set in the same font can measure differently: "Outlook" has
        no descender, so its ink extent is shorter than "Key Highlights" at an
        identical size. Dividing by the extent the text *could* occupy makes
        same-size lines compare equal, which is what heading detection needs.
        """
        return self.span / _extent_factor(self.text)

    @property
    def confidence(self) -> float:
        return sum(w.confidence for w in self.words) / len(self.words)

    @property
    def block(self) -> int:
        return self.words[0].block

    @property
    def paragraph(self) -> int:
        return self.words[0].paragraph

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2


@dataclass
class OcrPageResult:
    """OCR output for a single page or image."""

    markdown: str
    confidence: float
    word_count: int
    page_number: int = 1
    rotated_degrees: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.markdown.strip()


@dataclass
class OcrDocumentResult:
    """OCR output for a whole document."""

    markdown: str
    confidence: float
    word_count: int
    pages: int
    provider: str
    languages: str
    warnings: list[str] = field(default_factory=list)
