# Converter service: FastAPI + Microsoft MarkItDown + Tesseract OCR.
#
# Two stages so the build toolchain never reaches the runtime image. The
# runtime carries the Tesseract binary and only the two language packs we
# actually support, which is why this is a ~600 MB image rather than the
# several gigabytes a torch-based OCR stack would need.

# --- build ------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Compilers are needed by a few wheels and are discarded with this stage.
RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY services/converter/pyproject.toml ./

# Install into a virtualenv that is copied wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip setuptools wheel \
    && pip install "markitdown[all]==0.1.7" \
        "fastapi==0.115.6" \
        "uvicorn[standard]==0.34.0" \
        "python-multipart==0.0.20" \
        "pydantic-settings==2.7.1" \
        "pytesseract==0.3.13" \
        "pypdfium2>=5.9.0" \
        "pillow>=12.2.0" \
        "numpy>=2.2.1"

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# tesseract-ocr-eng and -ben are the language packs the product promises.
# Adding a language later is one more package here, with no code change.
RUN apt-get update && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-ben \
        libjpeg62-turbo \
        zlib1g \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged runtime user: uploads are untrusted input, and nothing this
# service does requires root.
RUN groupadd --system --gid 10001 converter \
    && useradd --system --uid 10001 --gid converter --no-create-home converter

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

WORKDIR /app
COPY --chown=converter:converter services/converter/app ./app
# The shared format registry, resolved by app/conversion/registry.py.
COPY --chown=converter:converter packages/formats ./packages/formats

# Temporary workspace. Mounted as a tmpfs in compose so uploads live in RAM
# and cannot survive a container restart.
ENV WORKSPACE_ROOT=/var/tmp/markpilot
RUN mkdir -p ${WORKSPACE_ROOT} && chown converter:converter ${WORKSPACE_ROOT}

USER converter
EXPOSE 8000

# /health is deliberately cheap: it checks liveness without touching documents.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--no-access-log"]
