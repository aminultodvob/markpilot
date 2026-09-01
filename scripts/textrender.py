"""Complex-script text rendering for test fixtures.

Pillow can only shape complex scripts when it was built against libraqm, which
is not guaranteed on every developer machine. Bengali needs real shaping -
`ি` reorders to the left of its consonant and `ো` splits around it - so text
drawn without it produces images that are *wrong*, and OCR run against them
would be measuring the renderer's bug rather than the recogniser's accuracy.

This module does the shaping explicitly with HarfBuzz and rasterises the
resulting glyphs with FreeType, so fixtures are correct everywhere.

Fixture tooling only: it is not imported by the service at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import freetype
import numpy as np
import uharfbuzz as hb
from PIL import Image

# HarfBuzz reports positions in 26.6 fixed point.
_FIXED = 64.0


@dataclass(frozen=True)
class ShapedGlyph:
    glyph_id: int
    x: float
    y: float


@lru_cache(maxsize=16)
def _load_font_bytes(font_path: str) -> bytes:
    return Path(font_path).read_bytes()


@lru_cache(maxsize=16)
def _hb_font(font_path: str, size: int) -> hb.Font:
    face = hb.Face(_load_font_bytes(font_path))
    font = hb.Font(face)
    font.scale = (int(size * _FIXED), int(size * _FIXED))
    return font


@lru_cache(maxsize=16)
def _ft_face(font_path: str, size: int) -> freetype.Face:
    face = freetype.Face(font_path)
    face.set_char_size(int(size * _FIXED))
    return face


def shape(text: str, font_path: str, size: int) -> tuple[list[ShapedGlyph], float]:
    """Shape ``text``, returning positioned glyphs and the total advance."""
    font = _hb_font(font_path, size)
    buffer = hb.Buffer()
    buffer.add_str(text)
    # Infers script, language and direction from the codepoints themselves.
    buffer.guess_segment_properties()
    hb.shape(font, buffer)

    glyphs: list[ShapedGlyph] = []
    pen_x = pen_y = 0.0
    for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions):
        glyphs.append(
            ShapedGlyph(
                glyph_id=info.codepoint,
                x=pen_x + pos.x_offset / _FIXED,
                y=pen_y + pos.y_offset / _FIXED,
            )
        )
        pen_x += pos.x_advance / _FIXED
        pen_y += pos.y_advance / _FIXED
    return glyphs, pen_x


def text_width(text: str, font_path: str, size: int) -> float:
    return shape(text, font_path, size)[1]


def draw_text(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    font_path: str,
    size: int,
    fill: int = 0,
) -> float:
    """Draw shaped ``text`` onto a grayscale image. Returns the advance width.

    ``xy`` is the top-left of the text's em box, matching PIL's convention so
    fixture code reads the same as it would with ``ImageDraw.text``.
    """
    if image.mode != "L":
        raise ValueError("draw_text expects a grayscale ('L') image")

    glyphs, advance = shape(text, font_path, size)
    face = _ft_face(font_path, size)
    # A copy, because a view onto a PIL image is read-only; pasted back below.
    canvas = np.array(image, dtype=np.uint8)
    # Baseline sits one ascender below the requested top edge.
    baseline_y = xy[1] + int(face.size.ascender / _FIXED)

    for glyph in glyphs:
        face.load_glyph(glyph.glyph_id, freetype.FT_LOAD_RENDER)
        bitmap = face.glyph.bitmap
        if bitmap.width == 0 or bitmap.rows == 0:
            continue

        coverage = np.array(bitmap.buffer, dtype=np.uint8).reshape(
            bitmap.rows, bitmap.pitch
        )[:, : bitmap.width]

        left = int(xy[0] + glyph.x + face.glyph.bitmap_left)
        top = int(baseline_y - glyph.y - face.glyph.bitmap_top)

        # Clip against the canvas so a glyph at the edge cannot overflow.
        x0, y0 = max(left, 0), max(top, 0)
        x1 = min(left + bitmap.width, canvas.shape[1])
        y1 = min(top + bitmap.rows, canvas.shape[0])
        if x0 >= x1 or y0 >= y1:
            continue

        patch = coverage[y0 - top : y1 - top, x0 - left : x1 - left].astype(np.float32)
        patch /= 255.0
        region = canvas[y0:y1, x0:x1].astype(np.float32)
        # Alpha-composite the glyph's coverage over the existing pixels.
        canvas[y0:y1, x0:x1] = (region * (1.0 - patch) + fill * patch).astype(np.uint8)

    image.paste(Image.fromarray(canvas, mode="L"))
    return advance
