# Deploying MarkPilot free on Render + Vercel

Render runs the Python converter (it needs Tesseract, so it has to be a
container). Vercel runs the Next.js app. Both fit inside the free tiers.

```
  Browser
    │
    ├── page ─────────────> Vercel      (Next.js app)
    │
    └── upload / convert ─> Render      (FastAPI + Tesseract)
```

---

## Why the browser uploads straight to Render

Self-hosted, the browser only ever talks to Next.js, which proxies to a
converter that has no public port. That is the better design and it is still
the default.

It cannot work on Vercel's free tier. **A Vercel serverless function accepts a
request body of at most 4.5 MB**, and the upload passes through the function
on its way to the converter. No amount of streaming or timeout tuning gets
around a platform limit, so a proxied upload of any real PDF fails.

Setting `NEXT_PUBLIC_CONVERTER_URL` switches the client to upload directly to
Render, which has no such limit. The cost is a publicly reachable converter,
which is why `CORS_ORIGINS` and the rate limits below are doing real work.

---

## 1. Render — the converter

**New → Blueprint**, point it at this repository. `render.yaml` configures
everything except the one value Render cannot guess.

Or configure it by hand: **New → Web Service**, then

| Setting | Value |
| --- | --- |
| Language / runtime | **Docker** |
| Dockerfile path | `./docker/converter.Dockerfile` |
| Docker build context | `.` (the repository root) |
| Health check path | `/health` |
| Instance type | Free |

The build context **must** be the repository root, not `services/converter` —
the image copies `packages/formats/formats.json`, which lives outside the
service directory.

Then set the environment variables from
[`.env.production.example`](../.env.production.example) §1. The one that is
not optional:

```
CORS_ORIGINS=https://markpilot.replyot.com
```

Without your web app's exact origin there, the browser's request is blocked
before it reaches your code, and the app looks broken with nothing in the
server logs.

Verify:

```bash
curl -s https://your-service.onrender.com/ready
```

`ocr.available` should be `true` and `ocr.languages` should list `ben` and
`eng`. The first request after an idle period takes ~35 seconds; see
[Cold starts](#cold-starts).

---

## 2. Vercel — the web app

**Add New → Project**, import the repository, then:

| Setting | Value |
| --- | --- |
| Framework preset | Next.js |
| **Root Directory** | **`apps/web`** |
| Include files outside root directory | **enabled** |
| Build / install command | leave as detected |

Root Directory has to be `apps/web`, and the app imports
`packages/formats/formats.json` from above it, so files outside the root must
be included. (Vercel enables that by default for monorepos.)

Environment variables — set all three for Production, Preview and Development:

```
NEXT_PUBLIC_CONVERTER_URL=https://your-service.onrender.com
NEXT_PUBLIC_SITE_URL=https://markpilot.replyot.com
CONVERTER_API_URL=https://your-service.onrender.com
```

`NEXT_PUBLIC_*` values are compiled into the browser bundle, so **changing
them requires a redeploy** — an env-var edit alone will not take effect.
Neither may ever hold a secret.

**Do not set `NEXT_OUTPUT_STANDALONE`.** See below.

---

## Troubleshooting

### Every API route returns 404, but pages load fine

This was the original failure here. `output: "standalone"` in
`next.config.ts` replaces per-route serverless functions with a single
self-contained server bundle. On Vercel the static pages still serve, so the
site looks deployed, while every dynamic route — including the API proxy —
returns Next's HTML 404.

The give-away is a response with `X-Matched-Path: /api/converter/[...path]`
and `Content-Type: text/html`: routing found the route, but no function was
deployed behind it.

`next.config.ts` now enables standalone only when
`NEXT_OUTPUT_STANDALONE=true` **and** `VERCEL` is unset, so Vercel gets
functions and Docker still gets a slim image.

### Uploads fail, or fail only for larger files

Either `NEXT_PUBLIC_CONVERTER_URL` is unset — so the upload goes through the
Vercel function and hits the 4.5 MB body cap — or it is set but the build
predates it. Set it and **redeploy**.

### "We couldn't reach the converter"

Almost always CORS. Check for the header:

```bash
curl -s -D - -o /dev/null -X OPTIONS \
  -H "Origin: https://your-app.vercel.app" \
  -H "Access-Control-Request-Method: POST" \
  https://your-service.onrender.com/api/v1/jobs | grep -i access-control-allow-origin
```

No `access-control-allow-origin` line means your origin is not in
`CORS_ORIGINS`. It must match exactly: scheme included, no trailing slash.

For Vercel's generated preview domains, add a regex — anchored at both ends,
or it will also match `https://markpilot-x.vercel.app.attacker.com`:

```
CORS_ORIGIN_REGEX=^https://markpilot-[a-z0-9-]+\.vercel\.app$
```

### Cold starts

A free Render service is suspended after ~15 minutes idle and takes roughly
35 seconds to wake. The web app pings `/health` when the converter UI mounts,
so that wait usually overlaps with choosing a file. The proxy route also sets
`maxDuration = 60`, because the platform default of 10 s would abort a cold
start as a gateway error.

If you need it always warm, an external uptime pinger every 10 minutes works,
or upgrade the instance.

### Converting a scanned PDF is slow (stuck on "Reading text")

That status means OCR is running: the PDF has no text layer, so every page is
rasterised and recognised by Tesseract. OCR is CPU-bound, and Render's free
instance is a fraction of a shared CPU — so a page that takes ~2 s on a normal
machine can take 15–25 s there, and a multi-page scan can even hit
`MAX_CONVERSION_TIME_SECONDS` and fail.

Two settings cut the work sharply, and `render.yaml` already applies both:

- `OCR_DETECT_ORIENTATION=false` — skips a whole extra Tesseract pass per page
  that only matters for sideways phone photos. On upright scans this measured
  **~60 % faster with identical accuracy**. This is the biggest lever.
- `OCR_DPI=150` — fewer pixels per page, so less CPU and less RAM than 200/300.

`OCR_DPI` takes effect from an env-var change alone; `OCR_DETECT_ORIENTATION`
needs this code deployed first. For genuinely fast OCR at volume, the real fix
is more CPU — a paid Render instance is several times quicker.

### A conversion dies partway through a large scan

The free instance has 512 MB of RAM, and OCR is the memory-hungry part: one
300-DPI page is a ~25 MB bitmap before Tesseract's own working set. The
supplied values (`OCR_DPI=150`, `OCR_MAX_PAGES=20`,
`MAX_CONCURRENT_CONVERSIONS=1`) are what keep it inside the limit. Lower
`OCR_DPI` further or reduce `OCR_MAX_PAGES` if you still see restarts.

### OCR reports unavailable

Check that `TESSERACT_CMD` and `TESSDATA_PREFIX` are **not** set on Render.
The image installs Tesseract with the `eng` and `ben` packs on the default
path; a leftover Windows path from local development overrides it and breaks
OCR.

---

## Security checklist for a public deployment

The converter is publicly reachable in this setup, so:

- [ ] `CORS_ORIGINS` lists only your own origins, and any regex is anchored
      with `^` and `$`.
- [ ] `RATE_LIMIT_ENABLED=true`. This is the only thing standing between an
      anonymous converter and someone else's batch job.
- [ ] `TRUST_PROXY_HEADERS=true` on Render — it sets `X-Forwarded-For`, and
      without this the limiter sees every request as one client.
- [ ] `MARKITDOWN_PLUGINS_ENABLED=false`. Plugins run arbitrary code against
      untrusted uploads.
- [ ] `APP_ENV=production`, which disables the `/docs` API explorer.
- [ ] No secrets in any `NEXT_PUBLIC_*` variable — they ship to the browser.
- [ ] `VISION_OCR_ENABLED=false` unless you intend to send page images to a
      third party, and you have said so in your privacy notice.
