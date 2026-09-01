"""Fetch Tesseract language data for local development.

The Docker image installs language packs through apt, so this script is only
for developing on a machine where the Tesseract installer shipped English but
not Bengali - the Windows UB-Mannheim build, most commonly.

Files are downloaded into ``services/converter/tessdata`` and are gitignored;
point the service at them with ``TESSDATA_PREFIX``.

Usage::

    python scripts/fetch_tessdata.py                  # eng, ben, osd
    python scripts/fetch_tessdata.py --languages deu  # add another
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESSDATA_DIR = REPO_ROOT / "services" / "converter" / "tessdata"

# tessdata_best is the Tesseract project's most accurate model set, published
# by tesseract-ocr under Apache-2.0. Worth the extra megabytes for Bengali,
# where the fast models are noticeably weaker.
BASE_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main"
DEFAULT_LANGUAGES = ("eng", "ben", "osd")

# Locations the Tesseract installers use, checked before downloading.
LOCAL_TESSDATA_CANDIDATES = (
    Path("C:/Program Files/Tesseract-OCR/tessdata"),
    Path("/usr/share/tesseract-ocr/5/tessdata"),
    Path("/usr/share/tessdata"),
    Path("/opt/homebrew/share/tessdata"),
)


def _copy_from_local_install(language: str, destination: Path) -> bool:
    """Reuse an already-installed model rather than re-downloading it."""
    for candidate in LOCAL_TESSDATA_CANDIDATES:
        source = candidate / f"{language}.traineddata"
        if source.is_file():
            shutil.copy2(source, destination)
            print(f"  {language}: copied from {candidate}")
            return True
    return False


def fetch(language: str, *, force: bool = False) -> bool:
    destination = TESSDATA_DIR / f"{language}.traineddata"
    if destination.is_file() and not force:
        print(f"  {language}: already present")
        return True

    if not force and _copy_from_local_install(language, destination):
        return True

    url = f"{BASE_URL}/{language}.traineddata"
    print(f"  {language}: downloading {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            if response.status != 200:
                print(f"  {language}: HTTP {response.status}", file=sys.stderr)
                return False
            data = response.read()
    except Exception as exc:
        print(f"  {language}: download failed - {exc}", file=sys.stderr)
        return False

    if len(data) < 100_000:
        print(f"  {language}: response too small to be a model", file=sys.stderr)
        return False

    destination.write_bytes(data)
    print(f"  {language}: saved {len(data):,} bytes")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--languages",
        nargs="*",
        default=list(DEFAULT_LANGUAGES),
        help=f"language codes (default: {' '.join(DEFAULT_LANGUAGES)})",
    )
    parser.add_argument("--force", action="store_true", help="re-fetch even if present")
    args = parser.parse_args()

    TESSDATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Tessdata directory: {TESSDATA_DIR}")

    failures = [lang for lang in args.languages if not fetch(lang, force=args.force)]
    if failures:
        print(f"\nFailed: {', '.join(failures)}", file=sys.stderr)
        return 1

    print(
        "\nDone. Point the service at these models with:\n"
        f"  TESSDATA_PREFIX={TESSDATA_DIR}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
