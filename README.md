# MarkPilot

**Turn documents into AI-ready Markdown.**

Convert PDF, Word, PowerPoint, Excel, images, and structured files into clean
Markdown for AI workflows, RAG pipelines, knowledge bases, and developer tools.
Scanned documents and photographs are read with OCR automatically — in English
and Bengali — with no account, no setup, and no permanent file storage.

> MarkPilot is an independent web interface built on the open-source
> [Microsoft MarkItDown](https://github.com/microsoft/markitdown) library. It is
> **not** affiliated with, endorsed by, or operated by Microsoft. See
> [docs/OPEN_SOURCE.md](docs/OPEN_SOURCE.md).

---

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Development](#development)
- [Environment variables](#environment-variables)
- [MarkItDown integration](#markitdown-integration)
- [OCR](#ocr)
- [Supported formats](#supported-formats)
- [Security](#security)
- [Temporary files and cleanup](#temporary-files-and-cleanup)
- [Testing](#testing)
- [Docker and deployment](#docker-and-deployment)
- [Free hosting (Render + Vercel)](#free-hosting-render--vercel)
- [API reference](#api-reference)
- [Licensing](#licensing)

---

## What it does

```
Open the site → drop files → format detected → OCR if needed
   → Markdown generated → preview → edit → copy or download → files deleted
```

There is no signup, no dashboard, and no document history. Uploads live in a
temporary session directory, are converted, and are removed.

**Highlights**

- **Real conversion, not a wrapper demo.** Uses the MarkItDown Python library
  directly, with three extra converters of our own where upstream has gaps.
- **OCR that reconstructs structure.** Scanned pages come back as headings,
  paragraphs, lists and tables — not a wall of loose words.
- **English and Bengali.** বাংলা is a first-class language, tested end to end
  for recognition accuracy and Unicode fidelity.
- **Honest progress.** Every status the UI shows comes from the server. There
  are no simulated progress bars.
- **Faithful output.** Nothing is summarised, rewritten, or invented. Uncertain
  OCR is flagged rather than smoothed over.

---

## Architecture

```
                             MARKPILOT
                              │
                              ▼
                     Next.js web app  (public, port 3000)
                              │
                              │  /api/converter/*  server-side proxy
                              ▼
                     FastAPI converter  (internal network only)
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
             File validation      Session manager
             (magic bytes,        (random ids, TTL,
              MIME, parse)         bearer tokens)
                    └─────────┬─────────┘
                              ▼
                     Temporary workspace
                              │
                              ▼
                     Format detection
                              │
                              ▼
                  Microsoft MarkItDown 0.1.7
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              Text extracted       No text layer
                    │                   │
                    │             OCR pipeline
                    │        (rasterize → preprocess →
                    │         Tesseract → layout)
                    └─────────┬─────────┘
                              ▼
                    Markdown normalization
                              │
                              ▼
                     Result (in memory)
                              │
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
              Preview       Edit       Download
                              │
                              ▼
                       Session cleanup
```

The converter service **publishes no port**. Only the Next.js app is reachable
from outside; it proxies API calls over the internal Docker network. The
conversion endpoint, which accepts file uploads, is never directly exposed.

### Layout

```
markpilot/
├── apps/web/                  Next.js 15 app (React 19, TypeScript, Tailwind 4)
│   ├── app/                   Routes, layout, proxy route handler
│   ├── components/            Converter, workspace, landing, theme
│   └── lib/                   API client, sanitizer, formats, types
├── services/converter/        FastAPI conversion service
│   ├── app/
│   │   ├── api/               Routes, schemas, dependencies
│   │   ├── conversion/        Engine, MarkItDown adapter, registry, normalize
│   │   ├── converters/        JSON, XML, IPYNB converters (gaps upstream)
│   │   ├── ocr/               Providers, preprocessing, layout, rasterize
│   │   ├── security/          Filenames, detection, archives, rate limiting
│   │   ├── sessions/          Session and job store
│   │   └── cleanup/           Background expiry worker
│   └── tests/                 144 tests: unit, integration, security, quality
├── packages/formats/          formats.json — shared format registry
├── scripts/                   Fixture generation, text shaping
├── fixtures/generated/        Synthetic test documents (generated)
├── docker/                    Dockerfiles
├── docs/                      OPEN_SOURCE.md
├── docker-compose.yml
└── .env.example
```

`packages/formats/formats.json` is the **single source of truth** for supported
formats, read by both the Python service and the web app. Adding a format is
one edit there.

---

## Quick start

### Docker (recommended)

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:3000>. The converter image includes Tesseract with the
English and Bengali language packs, so OCR works out of the box.

### Local development

Requirements: **Python 3.10+**, **Node 20.16+**, and **Tesseract 5** with the
`eng` and `ben` language data.

```bash
# 1. Tesseract
#    macOS:   brew install tesseract tesseract-lang
#    Debian:  sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-ben
#    Windows: winget install UB-Mannheim.TesseractOCR
#             then: python scripts/fetch_tessdata.py

# 2. Backend
cd services/converter
python -m venv .venv
.venv/bin/pip install -e ".[dev]"        # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --reload --port 8000

# 3. Frontend (in a second terminal)
cd apps/web
npm install
npm run dev
```

Then open <http://localhost:3000>.

Verify the backend found Tesseract:

```bash
curl -s http://localhost:8000/ready
```

`ocr.available` should be `true` and `ocr.languages` should list `ben` and `eng`.

---

## Development

All commands below are real and were used to build this project.

**Backend** (from `services/converter`):

```bash
.venv/bin/pytest                    # full suite (144 tests)
.venv/bin/pytest -m "not slow"      # skip the slower OCR passes
.venv/bin/ruff check app tests      # lint
.venv/bin/mypy app                  # type check
```

**Frontend** (from `apps/web`):

```bash
npm run dev         # dev server
npm run build       # production build
npm run typecheck   # tsc --noEmit
npm run lint        # eslint
```

**Fixtures** (from the repository root):

```bash
python scripts/generate_fixtures.py
```

Regenerates all 23 synthetic test documents. The suite runs this automatically
if they are missing.

---

## Environment variables

Copy `.env.example` to `.env`. Every value has a working default; nothing must
be set to run the app.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `production` or `test`. Disables `/docs` in production. |
| `LOG_LEVEL` | `INFO` | Structured-log verbosity. |
| `CORS_ORIGINS` | `http://localhost:3000` | Origins allowed to call the API directly. Empty in Docker, since the web app proxies. |
| `TRUST_PROXY_HEADERS` | `false` | Honour `X-Forwarded-For`. Only enable behind a proxy you control. |
| `MAX_FILE_SIZE_MB` | `50` | Per-file upload cap, enforced as bytes arrive. |
| `MAX_TOTAL_UPLOAD_MB` | `200` | Total cap for one job. |
| `MAX_FILES_PER_JOB` | `20` | File-count cap for one job. |
| `MAX_ARCHIVE_SIZE_MB` | `100` | Largest accepted ZIP. |
| `MAX_ARCHIVE_FILES` | `100` | Entry-count cap inside a ZIP. |
| `MAX_ARCHIVE_UNCOMPRESSED_MB` | `400` | Zip-bomb budget for expanded bytes. |
| `MAX_ARCHIVE_COMPRESSION_RATIO` | `200` | Per-entry ratio cap. |
| `MAX_ARCHIVE_DEPTH` | `1` | Nested archives are not walked at depth 1. |
| `MAX_CONVERSION_TIME_SECONDS` | `300` | Cooperative per-file timeout. |
| `MAX_CONCURRENT_CONVERSIONS` | `4` | Worker-pool size; the main CPU/memory bound. |
| `MAX_OUTPUT_CHARACTERS` | `4000000` | Cap on generated Markdown. A small spreadsheet can expand into millions of words, which the upload limit does not bound. |
| `MARKITDOWN_PLUGINS_ENABLED` | `false` | Third-party MarkItDown plugins. Off by default — see [MarkItDown integration](#markitdown-integration). |
| `SESSION_TTL_MINUTES` | `30` | Session lifetime. |
| `CLEANUP_INTERVAL_SECONDS` | `120` | Background sweep interval. |
| `WORKSPACE_ROOT` | system temp | Temporary workspace. Must not be inside a web root. |
| `OCR_ENABLED` | `true` | Master OCR switch. |
| `OCR_LANGUAGES` | `eng+ben` | Default Tesseract languages. |
| `OCR_DPI` | `300` | PDF rasterization resolution. |
| `OCR_MAX_PAGES` | `100` | Page cap for one document. |
| `OCR_PDF_TEXT_THRESHOLD_CHARS_PER_PAGE` | `100` | Below this, a PDF page is treated as scanned. |
| `OCR_LOW_CONFIDENCE_THRESHOLD` | `70` | Below this mean confidence, the result carries a warning. |
| `TESSERACT_CMD` | unset | Path to the binary, if not on `PATH`. |
| `TESSDATA_PREFIX` | unset | Path to language data, if not in the default location. |
| `VISION_OCR_ENABLED` | `false` | Optional vision-model OCR provider. |
| `VISION_API_BASE_URL` / `VISION_API_KEY` / `VISION_MODEL` | unset | Required together to enable it. Server-side only. |
| `RATE_LIMIT_ENABLED` | `true` | Abuse protection for an anonymous service. |
| `RATE_LIMIT_JOBS_PER_HOUR` | `40` | Jobs per client per hour. |
| `RATE_LIMIT_UPLOADS_MB_PER_HOUR` | `500` | Upload volume per client per hour. |
| `CONVERTER_API_URL` | `http://localhost:8000` | Internal converter URL, used by the Next.js server only. |
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` | Public URL for canonical links and Open Graph. |

---

## MarkItDown integration

Pinned to **`markitdown[all]==0.1.7`**, verified against that version's actual
API (`convert_local`, `DocumentConverterResult`, `register_converter`).

Everything talks to `app/conversion/markitdown_adapter.py`, never to MarkItDown
directly, so the library can be upgraded without touching the API, OCR pipeline,
or job runner.

### What we add, and why

MarkItDown covers PDF, DOCX, PPTX, XLSX/XLS, HTML, CSV, EPUB and ZIP well. We
register three converters ahead of the built-ins for real gaps:

| Converter | Why |
| --- | --- |
| `JsonConverter` | MarkItDown has no JSON converter; `.json` falls through to plain text and is echoed verbatim. Ours emits headings, definition bullets, and tables for uniform record lists. |
| `XmlConverter` | Same gap for generic XML. Ours preserves hierarchy and attributes and turns repeated siblings into tables, parsing via `defusedxml` so XXE and billion-laughs are refused. |
| `IpynbConverter` | MarkItDown's notebook converter **discards cell outputs**. Ours keeps execution order and output streams, which is most of what makes a notebook worth reading. |

Two further capabilities MarkItDown does not provide are handled in `app/ocr`:
its `ImageConverter` only reads EXIF metadata (plus an optional vision LLM) and
does **no OCR**, and its `PdfConverter` is text-only.

### Plugins

MarkItDown discovers third-party plugins via the `markitdown.plugin` entry-point
group. That is arbitrary code executing against untrusted uploads, so it is
**disabled by default** (`MARKITDOWN_PLUGINS_ENABLED=false`). Enable it only
after auditing every installed plugin.

---

## OCR

OCR is automatic. Users never need to know the term.

### When it runs

```
PDF ──► extract text with MarkItDown
         │
         ├── meaningful text? (chars per page ≥ threshold)  ──► use it
         │
         └── no  ──► rasterize pages ──► OCR pipeline
```

Images always go to OCR. A normal text PDF never does, which is both faster and
more accurate than recognising it. `Advanced options → Text recognition` can
force OCR on or off.

### Pipeline

1. **Rasterize** (PDFs) with [pypdfium2](https://github.com/pypdfium2-team/pypdfium2),
   one page at a time so a large scan cannot exhaust memory.
2. **Preprocess** — *conditionally*. Each step measures first:
   - grayscale, always;
   - upscale, only for low-resolution pages;
   - denoise, only when a median filter measurably changes the page;
   - contrast stretch, only when Otsu shows ink and paper are genuinely close;
   - deskew, only when projection-profile variance clearly improves.
   If the processed page reads *worse* than the untouched one, the untouched
   one is kept.
3. **Recognise** with Tesseract, asking for positioned words rather than plain
   text, because the coordinates are what make structure possible.
4. **Reconstruct** — heading levels from normalized line height, lists from
   bullet and enumerator patterns (including Bengali digits), tables from column
   clustering, paragraphs reflowed using the right margin, and two-column
   reading order from a detected whitespace gutter.
5. **Report** — mean word confidence, with a visible warning below the
   threshold. Uncertainty is surfaced, never hidden.

### Languages

English (`eng`) and Bengali (`ben`), individually or together. The default is
`eng+ben`. Adding a language is one more Tesseract package plus an
`OCR_LANGUAGES` change — no code.

### Providers

```
OcrProvider
├── TesseractOcrProvider   local, default, no network
└── VisionOcrProvider      optional, off unless fully configured
```

Tesseract was chosen over PaddleOCR/EasyOCR on deployment cost (a small OS
package rather than a multi-gigabyte model download), licence (Apache-2.0), and
Bengali quality. The vision provider is opt-in, keeps its key server-side, and
is prompted strictly for transcription — it marks unreadable regions rather than
guessing.

---

## Supported formats

| Category | Formats |
| --- | --- |
| Documents | `.pdf` `.docx` `.pptx` `.xlsx` `.xls` |
| Data | `.csv` `.json` `.xml` |
| Web | `.html` `.htm` |
| Technical | `.ipynb` `.epub` |
| Images (OCR) | `.png` `.jpg` `.jpeg` `.webp` |
| Archives | `.zip` |

A `.zip` is expanded and each supported member converted separately; unsupported
members are skipped and reported.

**Not supported: legacy `.doc` and `.ppt`.** MarkItDown 0.1.7 ships
`XlsConverter` for legacy `.xls` but has no converter for the binary Word or
PowerPoint formats. Rather than advertise them and fail after the upload, they
are rejected immediately with a message telling the user to save as `.docx` or
`.pptx`. A regression test asserts that every format we advertise actually has
a converter that accepts it, so this cannot drift.

---

## Security

Every upload is treated as hostile.

**Format detection does not trust filenames.** A file is accepted only if its
declared extension, MIME type, magic bytes *and* actual parsability agree. The
ZIP-based formats (`.docx`/`.pptx`/`.xlsx`/`.epub`/`.zip`) share one signature
and are told apart by inspecting the container; the OLE2 formats
(`.doc`/`.xls`/`.ppt`) by their storage streams. `invoice.pdf` containing a PNG
is rejected.

**Filenames never become paths.** Every stored file is named with a generated
id. The uploaded name is metadata used only for display and download, after
sanitization that strips path components (both separators), control characters,
Windows device names, and leading dots.

**Archives.** Zip Slip (`..`, absolute paths, drive letters, UNC), symlink
entries, zip bombs (both a global uncompressed budget and a per-entry ratio cap,
enforced *while streaming* rather than by trusting declared sizes), entry-count
floods, and nested-archive recursion are all refused.

**Markdown XSS.** Converted Markdown is untrusted. The preview parses Markdown,
sanitizes the resulting HTML with DOMPurify against an allowlist, and only then
inserts it. `javascript:` and `data:` URLs are stripped, external links get
`rel="noopener noreferrer nofollow"`, and script/iframe/object/embed/svg/form
are removed. The Markdown *itself* is left untouched so downloads stay faithful
— safety is applied at render time, where it is actually needed.

**Access control.** Results are reachable only through the session that created
them, via a random bearer token compared in constant time. No endpoint anywhere
accepts a path. Unknown session and wrong token return the same error, so valid
ids cannot be probed.

**Resource limits.** File size (enforced as bytes arrive, not from
`Content-Length`), total upload size, file count, page count, conversion
timeout, and a bounded worker pool. Rate limiting is per-client and in-memory,
keyed by a salted hash so raw IPs are never retained.

**XXE.** XML parses through `defusedxml`, so entity expansion and external
entities are refused.

---

## Temporary files and cleanup

There is no database. Nothing about a document is persisted.

```
<temp>/markpilot/<random-session-id>/
    uploads/     the uploaded bytes, named by generated id
    working/     archive extraction, page-range slices
    outputs/     reserved
```

Converted Markdown is held **in memory**, not written to disk, so it disappears
with the process.

A file is removed at the earliest of:

- immediately after it converts successfully;
- when the user clears the session;
- when the tab closes (the browser signals the server);
- when the session TTL expires;
- when the service restarts.

A background worker sweeps expired sessions on a timer and also removes
**orphaned** workspace directories — the crash-recovery path for files left
behind by a process that died.

Logs record shape and outcome only: format, size, duration, success or failure,
error category, and whether OCR ran. Document text, generated Markdown, and full
filenames are never logged.

---

## Testing

```bash
cd services/converter && .venv/bin/pytest
```

**144 tests**, covering:

- **Unit** — filename sanitization, format detection, the converter registry,
  the MarkItDown adapter, OCR provider selection and language resolution,
  Markdown normalization, page-range parsing, layout reconstruction.
- **Security** — path traversal, mislabelled files, container disambiguation,
  Zip Slip, zip bombs, symlink entries, archive limits, XXE, oversized uploads,
  cross-session access, session guessing, rate limiting.
- **Integration** — the whole journey: upload → convert → poll → read →
  download → ZIP → clear, plus archive expansion, partial failure, retry,
  cancellation, and session expiry.
- **Quality** — not just HTTP 200. Each format is asserted on its *content*:
  headings, tables, list items, code fences, worksheet names, slide titles,
  notebook outputs, and Unicode fidelity.
- **OCR** — recognition accuracy against known fixture text in English and
  Bengali, mixed-script pages, table extraction, multi-column reading order,
  skew correction, low-quality scans, and a regression test that preprocessing
  never degrades a clean page.

Fixtures are synthetic and generated by `scripts/generate_fixtures.py`; no
copyrighted documents are included. Bengali fixtures are shaped with HarfBuzz,
because rendering Bengali without shaping produces images whose glyphs are in
the wrong order — OCR against those would measure the renderer, not the
recogniser.

---

## Docker and deployment

```bash
docker compose up --build
```

- The **converter publishes no port**; it is reachable only from the web
  container over the internal network.
- Both containers run as **non-root**, with `read_only` root filesystems,
  `cap_drop: ALL`, and `no-new-privileges`.
- The workspace is a **tmpfs** mounted `noexec,nosuid`, so uploads live in RAM,
  cannot be executed, and never survive a restart.
- Both services declare **health checks**; the web app waits for the converter
  to be healthy.
- CPU and memory limits bound a single container's blast radius.

Behind a reverse proxy, terminate TLS there, forward to the `web` service, and
set `NEXT_PUBLIC_SITE_URL` to the public origin. Set `TRUST_PROXY_HEADERS=true`
**only** if the proxy overwrites `X-Forwarded-For`.

The runtime image is built with `NEXT_OUTPUT_STANDALONE=true`, which is what
keeps `node_modules` out of it. That flag must **not** be set on a managed Next
host - see below.

---

## Free hosting (Render + Vercel)

Render runs the converter (it needs Tesseract, so it must be a container) and
Vercel runs the web app. Both fit in the free tiers.

Two files exist for this:

- **[`render.yaml`](render.yaml)** - a Render blueprint with the whole service
  configured, tuned for the free plan's 512 MB and shared CPU.
- **[`.env.production.example`](.env.production.example)** - every production
  variable for both platforms, annotated with why each value is what it is.

Full walkthrough and troubleshooting: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

Two things about that setup are worth knowing before you start:

**The browser uploads directly to Render.** A Vercel serverless function
accepts a request body of at most 4.5 MB, and a proxied upload passes through
one, so any real document fails. Setting `NEXT_PUBLIC_CONVERTER_URL` makes the
client call the converter directly instead. The trade-off is a publicly
reachable converter, which is why `CORS_ORIGINS` and the rate limits are
load-bearing there rather than decorative. Self-hosted, leave that variable
empty and the private proxy is used.

**Never set `NEXT_OUTPUT_STANDALONE` on Vercel.** Standalone output replaces
per-route serverless functions with one server bundle; the symptom is that
static pages load normally while every API route returns 404. `next.config.ts`
detects Vercel and refuses to enable it regardless.

---

## API reference

The converter API is internal. The browser reaches it through the Next.js proxy
at `/api/converter/*`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness. Does no work. |
| `GET` | `/ready` | Readiness: workspace writable, OCR status. |
| `GET` | `/api/v1/formats` | The format registry and current limits. |
| `POST` | `/api/v1/jobs` | Multipart upload; creates a session and starts conversion. |
| `GET` | `/api/v1/jobs/{job_id}` | Poll job and per-file status. |
| `GET` | `/api/v1/jobs/{job_id}/files/{file_id}` | Markdown and metadata for one file. |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Stop a running job. |
| `POST` | `/api/v1/jobs/{job_id}/files/{file_id}/retry` | Re-run one file from the session copy. |
| `GET` | `/api/v1/jobs/{job_id}/files/{file_id}/download` | Download one `.md`. |
| `POST` | `/api/v1/jobs/{job_id}/download` | Download all results as a ZIP, including edits. |
| `DELETE` | `/api/v1/sessions/{session_id}` | Delete the session and its files immediately. |

All endpoints except `/health`, `/ready` and `/api/v1/formats` require
`X-Session-Id` and `X-Session-Token`, returned by `POST /api/v1/jobs`.

Example result:

```json
{
  "id": "9f2c1a...",
  "filename": "annual-report.pdf",
  "output_filename": "annual-report.md",
  "format": "pdf",
  "status": "completed",
  "markdown": "# Annual Report 2026\n\n## Executive Summary\n...",
  "metadata": {
    "format": "pdf",
    "label": "PDF",
    "pages": 10,
    "ocr_used": true,
    "ocr_languages": "eng+ben",
    "ocr_confidence": 95.5,
    "duration_ms": 8200,
    "word_count": 1840,
    "engine": "markitdown 0.1.7 + ocr:tesseract"
  },
  "warnings": []
}
```

Errors are structured and never leak a path or a traceback:

```json
{ "error": { "code": "format_mismatch",
             "message": "This file's contents don't match its extension.",
             "detail": "content does not match a PDF file" } }
```

---

## Licensing

This project is MIT licensed. It depends on open-source software with its own
terms — most importantly **Microsoft MarkItDown** (MIT) and **Tesseract OCR**
(Apache-2.0). Full attribution, licences, and the reasoning behind each major
dependency choice are in **[docs/OPEN_SOURCE.md](docs/OPEN_SOURCE.md)**.
# markpilot
