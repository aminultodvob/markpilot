"""Optional vision-model OCR provider.

Entirely opt-in. It activates only when an endpoint, key and model are all
configured, and the service runs fully without it. The API key is read from the
server environment and never crosses to the browser or appears in a response.

The prompt constrains the model to *transcription*. This product converts
documents; it does not author them. The model is told to reproduce what is on
the page and to mark unreadable regions rather than guess at them, because a
plausible invention is worse than an honest gap.
"""

from __future__ import annotations

import base64
import io

from PIL.Image import Image

from app.config import Settings
from app.logging_setup import get_logger
from app.ocr.base import OcrProvider
from app.ocr.types import OcrPageResult

logger = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 120
MAX_IMAGE_DIMENSION = 2000

TRANSCRIPTION_PROMPT = (
    "Transcribe this page into Markdown exactly as it appears.\n\n"
    "Rules:\n"
    "- Reproduce the text verbatim. Do not summarise, translate, correct or "
    "add anything.\n"
    "- Preserve structure: use headings for headings, lists for lists, and "
    "Markdown tables for tables.\n"
    "- Keep the original language and script. Do not transliterate.\n"
    "- If a region is genuinely unreadable, write [unreadable] rather than "
    "guessing what it might say.\n"
    "- Output only the transcription, with no commentary or code fences around "
    "the whole document."
)


class VisionOcrProvider(OcrProvider):
    """Transcribes pages with an OpenAI-compatible multimodal endpoint."""

    name = "vision"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_available(self) -> bool:
        return self._settings.vision_configured

    def supported_languages(self) -> list[str]:
        # Vision models are not restricted to installed language packs.
        return ["auto"]

    def _encode(self, image: Image) -> str:
        prepared = image
        longest = max(prepared.size)
        if longest > MAX_IMAGE_DIMENSION:
            scale = MAX_IMAGE_DIMENSION / longest
            prepared = prepared.resize(
                (int(prepared.width * scale), int(prepared.height * scale))
            )
        if prepared.mode not in ("RGB", "L"):
            prepared = prepared.convert("RGB")

        buffer = io.BytesIO()
        prepared.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def recognize(
        self, image: Image, *, languages: str, page_number: int = 1
    ) -> OcrPageResult:
        import httpx

        settings = self._settings
        payload = {
            "model": settings.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TRANSCRIPTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{self._encode(image)}"
                            },
                        },
                    ],
                }
            ],
            # Deterministic transcription, not creative writing.
            "temperature": 0,
        }

        try:
            response = httpx.post(
                f"{settings.vision_api_base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.vision_api_key}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            markdown = response.json()["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            # Never surface provider internals or the key to the caller.
            logger.warning(
                "vision OCR request failed",
                extra={"page": page_number, "error_type": type(exc).__name__},
            )
            return OcrPageResult(
                markdown="",
                confidence=0.0,
                word_count=0,
                page_number=page_number,
                warnings=["The vision OCR provider was unavailable for this page."],
            )

        markdown = markdown.strip()
        warnings: list[str] = []
        if "[unreadable]" in markdown:
            warnings.append("Some regions of this page could not be read.")

        return OcrPageResult(
            markdown=markdown,
            # Vision endpoints return no per-token confidence; report unknown
            # rather than inventing a number.
            confidence=-1.0,
            word_count=len(markdown.split()),
            page_number=page_number,
            warnings=warnings,
        )
