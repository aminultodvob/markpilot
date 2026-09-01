"""Image preprocessing for OCR.

Preprocessing is *conditional*. Applying every filter to every page reliably
makes clean documents worse - binarising an already-crisp scan throws away
antialiasing that Tesseract uses, and rotating by a mis-estimated fraction of a
degree smears glyph edges. So each step measures first and only acts when the
measurement says it will help.

Steps, in order:

1. grayscale (always - colour carries no signal for OCR);
2. upscale, when the page is too low-resolution for reliable recognition;
3. denoise, only when speckle is detected;
4. contrast enhancement, only when ink and paper are genuinely close together;
5. deskew, only when the estimated angle exceeds a threshold.

Denoise runs before the contrast step on purpose: salt-and-pepper pixels sit at
0 and 255 and would otherwise dominate the tonal measurement that decides
whether, and how far, to stretch.

Page *orientation* (90/180/270) is handled separately by the provider, which
can ask Tesseract's OSD model rather than guessing from pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter

# Below this width, characters are too few pixels tall for reliable OCR.
MIN_WIDTH_PX = 1400
MAX_WIDTH_PX = 4000
# Separation between the ink and paper populations, below which the page is
# genuinely faded. Measured via Otsu rather than by standard deviation: a clean
# document is overwhelmingly white, so its std is *low* precisely when its
# contrast is excellent, and treating that as "needs enhancement" wrecks it.
MIN_INK_PAPER_SEPARATION = 90.0
# Only correct skew we are reasonably sure about, and only small angles.
DESKEW_MIN_ANGLE = 0.35
DESKEW_MAX_ANGLE = 12.0
DESKEW_SEARCH_STEP = 0.25
# Mean absolute change a median filter makes, above which the page is speckled.
# Comparing against the filter's own output measures noise directly, instead of
# counting extreme pixels - most of which, on any document, are just paper.
DENOISE_DIFF_THRESHOLD = 6.0
# Decisions are made on a downsampled copy; full-resolution filtering is only
# paid for once the measurement says it is warranted.
DECISION_MAX_DIMENSION = 1200
# Noise, unlike grey levels, must be measured at native resolution.
PATCH_SIZE = 1000
# A skew estimate is only trusted if it beats the unrotated page by this much,
# and is not pinned to the edge of the search range - both are the signatures
# of noise driving the search rather than text lines.
DESKEW_MIN_IMPROVEMENT = 1.15


@dataclass
class PreprocessReport:
    """What was actually done, for logging and result warnings."""

    grayscale: bool = False
    upscaled: bool = False
    contrast_enhanced: bool = False
    denoised: bool = False
    deskewed: bool = False
    deskew_angle: float = 0.0
    steps: list[str] = field(default_factory=list)

    def record(self, step: str) -> None:
        self.steps.append(step)


def _to_grayscale(image: Image.Image) -> Image.Image:
    if image.mode == "L":
        return image
    # Flatten transparency onto white first, or alpha becomes black smears.
    if image.mode in ("RGBA", "LA", "P"):
        converted = image.convert("RGBA")
        background = Image.new("RGBA", converted.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, converted)
    return image.convert("L")


def _upscale(image: Image.Image, report: PreprocessReport) -> Image.Image:
    width, height = image.size
    if width >= MIN_WIDTH_PX or width == 0:
        return image
    scale = min(MIN_WIDTH_PX / width, MAX_WIDTH_PX / max(width, 1))
    if scale <= 1.05:
        return image
    new_size = (int(width * scale), int(height * scale))
    report.upscaled = True
    report.record(f"upscaled x{scale:.1f}")
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _downsample_for_decisions(image: Image.Image) -> Image.Image:
    """A small copy of the page, good enough to measure but cheap to process.

    Safe for grey-level statistics, which survive resampling. Not safe for
    noise measurement - see ``_full_resolution_patch``.
    """
    longest = max(image.size)
    if longest <= DECISION_MAX_DIMENSION:
        return image
    scale = DECISION_MAX_DIMENSION / longest
    return image.resize(
        (max(int(image.width * scale), 1), max(int(image.height * scale), 1)),
        Image.Resampling.BILINEAR,
    )


def _full_resolution_patch(image: Image.Image) -> Image.Image:
    """A centre crop at native resolution, for measuring noise.

    Downsampling averages neighbouring pixels, which is exactly what a denoise
    filter does - so speckle measured on a shrunk copy always looks absent.
    """
    width, height = image.size
    if width <= PATCH_SIZE and height <= PATCH_SIZE:
        return image
    left = max((width - PATCH_SIZE) // 2, 0)
    top = max((height - PATCH_SIZE) // 2, 0)
    return image.crop(
        (left, top, min(left + PATCH_SIZE, width), min(top + PATCH_SIZE, height))
    )


def _otsu_threshold(array: np.ndarray) -> int:
    """Grey level that best separates the image into two populations."""
    histogram = np.bincount(array.reshape(-1), minlength=256).astype(np.float64)
    total = histogram.sum()
    if total == 0:
        return 128

    levels = np.arange(256, dtype=np.float64)
    weight_bg = np.cumsum(histogram)
    weight_fg = total - weight_bg
    sum_total = float((histogram * levels).sum())
    sum_bg = np.cumsum(histogram * levels)

    valid = (weight_bg > 0) & (weight_fg > 0)
    if not valid.any():
        return 128

    mean_bg = np.divide(sum_bg, weight_bg, out=np.zeros(256), where=weight_bg > 0)
    mean_fg = np.divide(
        sum_total - sum_bg, weight_fg, out=np.zeros(256), where=weight_fg > 0
    )
    # Between-class variance; its maximum is Otsu's threshold.
    variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    variance[~valid] = -1.0
    return int(np.argmax(variance))


def _ink_and_paper(array: np.ndarray) -> tuple[float, float]:
    """Mean grey level of the ink and of the paper, split at Otsu's threshold."""
    threshold = _otsu_threshold(array)
    ink = array[array <= threshold]
    paper = array[array > threshold]
    if ink.size == 0 or paper.size == 0:
        return 0.0, 255.0
    return float(ink.mean()), float(paper.mean())


def _stretch_levels(image: Image.Image, low: float, high: float) -> Image.Image:
    """Map the range [low, high] onto the full 0-255 range, clipping outside.

    Deliberately not ``ImageOps.autocontrast``: that anchors on the global
    minimum and maximum, and a single speckle pixel at 0 and another at 255
    make the histogram already "full", so it does nothing at all on exactly
    the faded, noisy scans that need it most.
    """
    span = max(high - low, 1.0)
    table = [
        0 if value <= low else 255 if value >= high
        else int(round((value - low) * 255.0 / span))
        for value in range(256)
    ]
    return image.point(table)


def _enhance_contrast(
    image: Image.Image, small: np.ndarray, report: PreprocessReport
) -> Image.Image:
    ink, paper = _ink_and_paper(small)
    separation = paper - ink
    if separation >= MIN_INK_PAPER_SEPARATION:
        # Ink and paper are already well separated; leave the page alone.
        return image

    # Anchor slightly outside the two populations so their cores saturate to
    # solid black and solid white rather than dark-grey and light-grey.
    margin = separation * 0.35
    report.contrast_enhanced = True
    report.record(f"contrast stretched (ink {ink:.0f}, paper {paper:.0f})")
    return _stretch_levels(image, ink + margin, paper - margin)


def _denoise(image: Image.Image, report: PreprocessReport) -> Image.Image:
    patch = _full_resolution_patch(image)
    filtered = patch.filter(ImageFilter.MedianFilter(size=3))
    difference = float(
        np.abs(
            np.asarray(patch, dtype=np.int16) - np.asarray(filtered, dtype=np.int16)
        ).mean()
    )
    if difference < DENOISE_DIFF_THRESHOLD:
        return image

    report.denoised = True
    report.record(f"denoised (noise {difference:.1f})")
    # Median filter removes speckle while preserving stroke edges.
    return image.filter(ImageFilter.MedianFilter(size=3))


def _estimate_skew(array: np.ndarray) -> float:
    """Estimate skew via horizontal projection-profile variance.

    Text lines produce sharp peaks in the row-sum profile only when they are
    horizontal, so the angle maximising the profile's variance is the skew.
    """
    # Work on a downsampled binary image: this is a search, not a render.
    # The stride MUST be the same on both axes - sampling rows and columns at
    # different rates squashes the page and scales every angle by that ratio.
    stride = max(1, max(array.shape) // 600)
    small = array[::stride, ::stride]
    if small.size == 0:
        return 0.0
    threshold = float(small.mean()) - float(small.std()) * 0.5
    binary = (small < threshold).astype(np.float32)
    if binary.sum() < 50:
        return 0.0

    height, width = binary.shape
    centre_y, centre_x = height / 2.0, width / 2.0
    row_indices, column_indices = np.nonzero(binary)
    ys = row_indices.astype(np.float64) - centre_y
    xs = column_indices.astype(np.float64) - centre_x

    def score_at(angle: float) -> float:
        radians = np.deg2rad(angle)
        # Only the rotated y coordinate matters for a horizontal projection.
        rotated_y = xs * np.sin(radians) + ys * np.cos(radians)
        rows = np.clip((rotated_y + centre_y).astype(np.int32), 0, height - 1)
        return float(np.bincount(rows, minlength=height).astype(np.float32).var())

    upright_score = score_at(0.0)
    best_angle, best_score = 0.0, upright_score

    angle = -DESKEW_MAX_ANGLE
    while angle <= DESKEW_MAX_ANGLE:
        score = score_at(angle)
        if score > best_score:
            best_score, best_angle = score, angle
        angle += DESKEW_SEARCH_STEP

    # A noisy page has no sharp line structure, so the search wanders and tends
    # to settle at whichever extreme it reached last. Reject both signatures:
    # an estimate pinned to the edge of the range, and one that barely beats
    # leaving the page alone.
    if abs(best_angle) >= DESKEW_MAX_ANGLE - DESKEW_SEARCH_STEP:
        return 0.0
    if upright_score > 0 and best_score < upright_score * DESKEW_MIN_IMPROVEMENT:
        return 0.0
    return best_angle


def _deskew(
    image: Image.Image, array: np.ndarray, report: PreprocessReport
) -> Image.Image:
    angle = _estimate_skew(array)
    if abs(angle) < DESKEW_MIN_ANGLE:
        return image
    report.deskewed = True
    report.deskew_angle = angle
    report.record(f"deskewed {-angle:+.2f}deg")
    # Negated: the estimate is the skew the page *has*, so straightening it
    # means rotating back by that amount, not applying it again.
    # expand keeps corners; white fill matches paper so no false ink appears.
    return image.rotate(
        -angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255
    )


def preprocess(
    image: Image.Image, *, enabled: bool = True
) -> tuple[Image.Image, PreprocessReport]:
    """Return an OCR-ready image plus a report of the steps applied."""
    report = PreprocessReport()

    result = _to_grayscale(image)
    report.grayscale = result is not image
    if not enabled:
        return result, report

    result = _upscale(result, report)

    # Denoise first: speckle at 0 and 255 distorts the tonal measurement that
    # the contrast step depends on, so it has to go before levels are read.
    result = _denoise(result, report)

    small = _downsample_for_decisions(result)
    result = _enhance_contrast(result, np.asarray(small, dtype=np.uint8), report)
    if report.contrast_enhanced:
        small = _downsample_for_decisions(result)

    result = _deskew(result, np.asarray(small, dtype=np.uint8), report)
    return result, report
