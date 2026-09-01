# Open source attribution

MarkPilot is built on open-source software. This document records what
we depend on, under which licence, and — for each significant choice — why that
component rather than an alternative.

## Relationship to Microsoft

**MarkPilot is not a Microsoft product.**

It is an independent web interface built on
[Microsoft MarkItDown](https://github.com/microsoft/markitdown), an open-source
library published by Microsoft under the MIT licence. This project is not
affiliated with, endorsed by, sponsored by, or operated by Microsoft
Corporation. "MarkItDown" and "Microsoft" are the property of their respective
owners.

The distinction, stated plainly:

| | |
| --- | --- |
| **Microsoft MarkItDown** | The open-source Python library that performs document parsing. Published by Microsoft. |
| **MarkPilot** | This project: a hosted interface, OCR pipeline, security layer, and API built *around* that library. Independent. |

The MIT licence notice for MarkItDown is reproduced below and must be retained
in any distribution of this project.

---

## Core dependencies

### Microsoft MarkItDown — MIT

- Source: <https://github.com/microsoft/markitdown>
- Version: `0.1.7` (pinned exactly)
- Role: the document conversion engine, handling PDF, DOCX, PPTX, XLSX/XLS,
  HTML, CSV, EPUB, ZIP and more.

Pinned rather than ranged because our adapter is verified against this
version's API surface and its converter set determines which formats we can
advertise. Upgrades are a deliberate step, not an automatic one.

```
MIT License

Copyright (c) Microsoft Corporation.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

MarkItDown itself bundles further dependencies under its `[all]` extra —
`pdfminer.six`, `pdfplumber`, `python-pptx`, `mammoth`, `openpyxl`, `pandas`,
`beautifulsoup4`, `markdownify`, `defusedxml`, `magika`, `olefile`, `lxml`,
`xlrd` — each under its own permissive licence (MIT, BSD or Apache-2.0).

### Tesseract OCR — Apache-2.0

- Source: <https://github.com/tesseract-ocr/tesseract>
- Role: the local OCR engine, with the `eng` and `ben` language packs.

**Why Tesseract.** The product requires English *and* Bengali. The realistic
alternatives were:

| Option | Bengali | Deployment cost | Licence | Verdict |
| --- | --- | --- | --- | --- |
| **Tesseract** | Yes, good `ben` model | Small OS package (~50 MB with both packs) | Apache-2.0 | **Chosen** |
| EasyOCR | Yes | Pulls PyTorch, ~2.5 GB | Apache-2.0 | Rejected: image size |
| PaddleOCR | Partial | Large framework | Apache-2.0 | Rejected: size, weaker Bengali |
| RapidOCR | No Bengali | Small | Apache-2.0 | Rejected: misses a requirement |

Bengali language data (`ben.traineddata`) comes from the
[tessdata_best](https://github.com/tesseract-ocr/tessdata_best) repository,
published by the Tesseract project under Apache-2.0.

### pypdfium2 — Apache-2.0 / BSD-3-Clause

- Source: <https://github.com/pypdfium2-team/pypdfium2>
- Role: rendering PDF pages to images for OCR.

**Why not the obvious alternatives.** This choice was made on licensing and
deployment grounds, and is worth recording:

- **PyMuPDF** is the most common option and is excellent, but it is licensed
  **AGPL-3.0** (or a paid commercial licence). AGPL is a poor fit for a hosted
  web service, whose users interact with it over a network.
- **pdf2image** is MIT, but shells out to a **Poppler** binary that has to be
  installed separately, adding a system dependency and a subprocess per page.
- **pypdfium2** wraps Google's PDFium under permissive terms and ships a
  self-contained wheel with no system dependency.

### Pillow — MIT-CMU

- Source: <https://github.com/python-pillow/Pillow>
- Role: image loading, WebP support, and the preprocessing filters.

### FastAPI, Starlette, Uvicorn, Pydantic — MIT / BSD-3-Clause

The HTTP layer, ASGI server, and settings/validation models.

### NumPy — BSD-3-Clause

Used in preprocessing for Otsu thresholding, noise measurement, and the
projection-profile skew search.

### defusedxml — PSF-2.0

Ships with MarkItDown and is used directly by our XML converter and detector so
that entity expansion and external-entity attacks (billion laughs, XXE) are
refused rather than processed.

---

## Web application

| Package | Licence | Role |
| --- | --- | --- |
| [Next.js](https://github.com/vercel/next.js) | MIT | React framework, routing, server-side proxy |
| [React](https://github.com/facebook/react) | MIT | UI library |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) | MIT | Styling |
| [DOMPurify](https://github.com/cure53/DOMPurify) | Apache-2.0 / MPL-2.0 | HTML sanitization for the Markdown preview |
| [marked](https://github.com/markedjs/marked) | MIT | Markdown parsing |
| [CodeMirror 6](https://github.com/codemirror/dev) | MIT | The Markdown source editor |
| [Lucide](https://github.com/lucide-icons/lucide) | ISC | Icons |

**Why CodeMirror rather than Monaco.** Both are MIT. CodeMirror provides
everything this tool needs — syntax highlighting, line wrapping, search, undo,
keyboard navigation — at a fraction of the bundle size. Monaco's additional
capability (IntelliSense, multi-file models, language servers) is irrelevant for
editing a single Markdown document and would dominate page weight. The editor is
also lazily loaded, so it costs nothing until a conversion result exists.

**Why DOMPurify.** Converted documents are untrusted input and can carry script
payloads through conversion. DOMPurify is the most scrutinised HTML sanitizer
available and is used here with an explicit allowlist rather than its defaults.

---

## Development-only dependencies

These are not part of the runtime image.

| Package | Licence | Role |
| --- | --- | --- |
| pytest | MIT | Test runner |
| ruff | MIT | Linter |
| mypy | MIT | Type checker |
| httpx | BSD-3-Clause | Test client |
| reportlab | BSD-3-Clause | Generates PDF fixtures |
| python-docx | MIT | Generates DOCX fixtures |
| uharfbuzz | Apache-2.0 | Shapes Bengali text for OCR fixtures |
| freetype-py | FreeType (BSD-style) / GPLv2 | Rasterises shaped glyphs |
| ESLint, TypeScript | MIT / Apache-2.0 | Frontend linting and types |

**Why uharfbuzz and freetype-py.** Pillow can only shape complex scripts when
built against `libraqm`, which is not present in every environment. Bengali
requires real shaping — `ি` reorders to the left of its consonant, and `ো`
splits around it — so text drawn without it produces images that are simply
wrong. Running OCR against those would measure the renderer's bug rather than
the recogniser's accuracy. These two libraries do the shaping explicitly, and
are used only to build test fixtures.

---

## Fixtures and content

Every test fixture in `fixtures/generated/` is synthesised by
`scripts/generate_fixtures.py` from text written for this project. No
copyrighted or third-party documents are included in this repository.

Fonts are read from the host system at fixture-generation time and are **not**
redistributed here.

---

## Dependency policy

Each significant dependency was assessed against:

1. Does MarkItDown already provide this? (If yes, we do not reimplement it.)
2. Is it actively maintained?
3. Is the licence compatible with a hosted service? (This ruled out AGPL.)
4. How much attack surface does it add, given it processes untrusted input?
5. How much does it add to the container image?

The result is a deliberately small runtime dependency set. Nothing was included
because it is popular.
