"""Jupyter notebook to Markdown.

MarkItDown's own notebook converter keeps Markdown and code cells but discards
``outputs`` entirely, which loses the results that make a notebook worth
reading. This converter preserves execution order and the useful parts of each
output stream while staying faithful: nothing is summarised or invented, and
binary results (images, widgets) are noted rather than embedded.
"""

from __future__ import annotations

import json
from typing import Any, BinaryIO

from markitdown import DocumentConverter, DocumentConverterResult, StreamInfo

ACCEPTED_EXTENSIONS = (".ipynb",)
ACCEPTED_MIME_PREFIXES = ("application/x-ipynb+json",)

# Long outputs are truncated so one runaway loop cannot dominate the document.
MAX_OUTPUT_LINES = 40
MAX_OUTPUT_CHARS = 4000


def _source_to_text(source: Any) -> str:
    """Notebook ``source`` is either a string or a list of lines."""
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return str(source or "")


def _truncate(text: str) -> tuple[str, bool]:
    lines = text.split("\n")
    truncated = False
    if len(lines) > MAX_OUTPUT_LINES:
        lines = lines[:MAX_OUTPUT_LINES]
        truncated = True
    result = "\n".join(lines)
    if len(result) > MAX_OUTPUT_CHARS:
        result = result[:MAX_OUTPUT_CHARS]
        truncated = True
    return result.rstrip(), truncated


def _language(notebook: dict[str, Any]) -> str:
    metadata = notebook.get("metadata") or {}
    for path in (("kernelspec", "language"), ("language_info", "name")):
        node: Any = metadata
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, str) and node.strip():
            return node.strip().lower()
    return "python"


def _render_outputs(outputs: list[dict[str, Any]], lines: list[str]) -> None:
    rendered: list[str] = []
    notes: list[str] = []

    for output in outputs:
        kind = output.get("output_type")

        if kind == "stream":
            rendered.append(_source_to_text(output.get("text")))

        elif kind in ("execute_result", "display_data"):
            data = output.get("data") or {}
            if "text/plain" in data:
                rendered.append(_source_to_text(data["text/plain"]))
            image_types = [k for k in data if k.startswith("image/")]
            if image_types:
                # Embedding base64 images would bloat the Markdown for no gain.
                notes.append("_(image output omitted)_")
            if not data:
                notes.append("_(output omitted)_")

        elif kind == "error":
            name = str(output.get("ename", "Error"))
            value = str(output.get("evalue", ""))
            rendered.append(f"{name}: {value}".strip(": "))

    body = "\n".join(part for part in rendered if part.strip())
    if body.strip():
        text, truncated = _truncate(body)
        lines.extend(["Output:", "", "```", text, "```"])
        if truncated:
            lines.extend(["", "_(output truncated)_"])
        lines.append("")

    for note in dict.fromkeys(notes):
        lines.extend([note, ""])


def notebook_to_markdown(notebook: dict[str, Any]) -> tuple[str, str | None]:
    language = _language(notebook)
    lines: list[str] = []
    title: str | None = None

    for cell in notebook.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        cell_type = cell.get("cell_type")
        source = _source_to_text(cell.get("source")).strip("\n")

        if cell_type == "markdown":
            if not source.strip():
                continue
            if title is None:
                for line in source.split("\n"):
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            lines.extend([source, ""])

        elif cell_type == "code":
            if source.strip():
                count = cell.get("execution_count")
                if count is not None:
                    lines.append(f"**In [{count}]:**")
                    lines.append("")
                lines.extend([f"```{language}", source, "```", ""])
            outputs = cell.get("outputs")
            if isinstance(outputs, list) and outputs:
                _render_outputs(outputs, lines)

        elif cell_type == "raw" and source.strip():
            lines.extend(["```", source, "```", ""])

    return "\n".join(lines).strip() + "\n", title


class IpynbConverter(DocumentConverter):
    """Notebook converter that preserves cell outputs and execution order."""

    def accepts(
        self, file_stream: BinaryIO, stream_info: StreamInfo, **kwargs: Any
    ) -> bool:
        extension = (stream_info.extension or "").lower()
        mimetype = (stream_info.mimetype or "").lower()
        if extension in ACCEPTED_EXTENSIONS:
            return True
        if extension:
            return False
        return any(mimetype.startswith(p) for p in ACCEPTED_MIME_PREFIXES)

    def convert(
        self, file_stream: BinaryIO, stream_info: StreamInfo, **kwargs: Any
    ) -> DocumentConverterResult:
        charset = stream_info.charset or "utf-8"
        raw = file_stream.read().decode(charset, errors="replace")
        try:
            notebook = json.loads(raw)
        except json.JSONDecodeError:
            return DocumentConverterResult(markdown=f"```json\n{raw.strip()}\n```\n")

        markdown, title = notebook_to_markdown(notebook)
        return DocumentConverterResult(markdown=markdown, title=title)
