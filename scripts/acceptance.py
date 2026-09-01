"""End-to-end acceptance run against a live service.

Uploads every generated fixture through the real HTTP API and reports, per
format: status, whether OCR engaged, duration, output size, and a content check
that the Markdown actually contains what the fixture says it should.

Usage::

    python scripts/acceptance.py [--base-url http://127.0.0.1:3000/api/converter]

Point ``--base-url`` at the Next.js proxy to exercise the full public path, or
at the converter directly to isolate the backend.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures" / "generated"
TERMINAL = {"completed", "failed", "cancelled"}

# fixture -> substrings the converted Markdown must contain.
EXPECTATIONS: dict[str, list[str]] = {
    "text.pdf": ["Quarterly Update", "text layer", "Page Two"],
    "scanned-english.pdf": ["Annual Report", "Executive Summary", "Revenue"],
    "scanned-bengali.pdf": ["প্রতিবেদন"],
    "scanned-multipage.pdf": ["Annual Report", "Widget"],
    "proposal.docx": ["Project Proposal", "Objectives", "Engineering"],
    "deck.pptx": ["Market Overview", "Key Findings", "supply chain"],
    "workbook.xlsx": ["Sales", "Expenses", "Product A", "Marketing"],
    "book.epub": ["The Beginning", "The Middle"],
    "table.csv": ["Alpha", "50000", "| ---"],
    "records.json": ["Quarterly Report", "alpha", "| ---"],
    "catalog.xml": ["Catalog", "Deep Work", "Acme"],
    "page.html": ["Sample Page", "First item"],
    "notebook.ipynb": ["Analysis", "```python", "42"],
    "ocr-english.png": ["Annual Report", "Executive Summary"],
    "ocr-english.jpg": ["Annual Report"],
    "ocr-english.webp": ["Annual Report"],
    "ocr-bengali.png": ["প্রতিবেদন"],
    "ocr-mixed.png": ["Annual"],
    "ocr-table.png": ["Widget", "| ---"],
    "ocr-multicolumn.png": ["first column", "second column"],
    "ocr-skewed.png": ["Annual Report"],
    "ocr-low-quality.png": ["Faded", "1450"],
    "bundle.zip": ["Alpha"],
}

MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".ipynb": "application/x-ipynb+json",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".epub": "application/epub+zip",
}


def convert_one(client: httpx.Client, base: str, path: Path) -> dict:
    started = time.monotonic()
    with path.open("rb") as handle:
        response = client.post(
            f"{base}/api/v1/jobs",
            files=[("files", (path.name, handle, MIME.get(path.suffix, "application/octet-stream")))],
            data={"ocr_mode": "auto"},
            timeout=60.0,
        )
    if response.status_code != 201:
        return {"ok": False, "note": f"upload HTTP {response.status_code}"}

    created = response.json()
    headers = {
        "X-Session-Id": created["session_id"],
        "X-Session-Token": created["session_token"],
    }
    job_id = created["id"]

    deadline = time.monotonic() + 180
    job = created
    while time.monotonic() < deadline:
        job = client.get(f"{base}/api/v1/jobs/{job_id}", headers=headers).json()
        if job["status"] in TERMINAL:
            break
        time.sleep(0.2)

    elapsed = time.monotonic() - started
    markdown_parts: list[str] = []
    ocr_used = False
    confidences: list[float] = []

    for entry in job["files"]:
        if entry["status"] != "completed":
            continue
        result = client.get(
            f"{base}/api/v1/jobs/{job_id}/files/{entry['id']}", headers=headers
        ).json()
        markdown_parts.append(result["markdown"])
        meta = result["metadata"]
        ocr_used = ocr_used or meta.get("ocr_used", False)
        if meta.get("ocr_confidence") is not None:
            confidences.append(meta["ocr_confidence"])

    markdown = "\n".join(markdown_parts)
    expected = EXPECTATIONS.get(path.name, [])
    missing = [token for token in expected if token.lower() not in markdown.lower()]

    # Exercise the ZIP download path too.
    zip_ok = False
    if markdown_parts:
        archive = client.post(
            f"{base}/api/v1/jobs/{job_id}/download", headers=headers, json={"files": []}
        )
        if archive.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
                zip_ok = all(n.endswith(".md") for n in bundle.namelist())

    client.delete(f"{base}/api/v1/sessions/{created['session_id']}", headers=headers)

    completed = sum(1 for f in job["files"] if f["status"] == "completed")
    return {
        "ok": completed == len(job["files"]) and not missing and zip_ok,
        "status": job["status"],
        "files": f"{completed}/{len(job['files'])}",
        "ocr": ocr_used,
        "confidence": round(sum(confidences) / len(confidences), 1) if confidences else None,
        "seconds": round(elapsed, 2),
        "chars": len(markdown),
        "missing": missing,
        "zip_ok": zip_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    paths = sorted(p for p in FIXTURES.iterdir() if p.name in EXPECTATIONS)
    if not paths:
        print("No fixtures found. Run scripts/generate_fixtures.py first.")
        return 1

    print(f"Acceptance run against {base}\n")
    header = f"{'fixture':<24} {'result':<7} {'files':<6} {'ocr':<5} {'conf':<6} {'time':<8} {'chars':<7} notes"
    print(header)
    print("-" * len(header))

    failures = 0
    total_time = 0.0
    for path in paths:
        outcome = convert_one(httpx.Client(), base, path)
        total_time += outcome.get("seconds", 0.0)
        ok = outcome["ok"]
        failures += 0 if ok else 1
        notes = ""
        if outcome.get("missing"):
            notes = "missing: " + ", ".join(outcome["missing"][:3])
        elif not outcome.get("zip_ok", True):
            notes = "zip download failed"
        elif "note" in outcome:
            notes = outcome["note"]
        confidence = outcome.get("confidence")
        print(
            f"{path.name:<24} {'PASS' if ok else 'FAIL':<7} "
            f"{outcome.get('files', '-'):<6} "
            f"{'yes' if outcome.get('ocr') else 'no':<5} "
            f"{(str(confidence) if confidence is not None else '-'):<6} "
            f"{outcome.get('seconds', 0):<8.2f} {outcome.get('chars', 0):<7} {notes}"
        )

    print("-" * len(header))
    print(
        f"{len(paths) - failures}/{len(paths)} passed  ·  "
        f"total {total_time:.1f}s  ·  mean {total_time / len(paths):.2f}s per document"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
