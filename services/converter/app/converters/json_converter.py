"""JSON to Markdown.

MarkItDown has no JSON converter - a .json file falls through to the plain-text
converter and is emitted verbatim, which is not Markdown in any useful sense.

This converter reads the *shape* of the document and picks a representation:

* a list of flat records with consistent keys becomes a table;
* nested objects become headings, with scalar leaves as definition bullets;
* anything too deep, too irregular or too large to present usefully falls back
  to a fenced ``json`` block, which is the honest rendering for
  machine-generated payloads.
"""

from __future__ import annotations

import json
from typing import Any, BinaryIO

from markitdown import DocumentConverter, DocumentConverterResult, StreamInfo

ACCEPTED_EXTENSIONS = (".json",)
ACCEPTED_MIME_PREFIXES = ("application/json", "text/json")

MAX_HEADING_DEPTH = 4
MIN_TABLE_ROWS = 2
MAX_TABLE_COLUMNS = 12
# Beyond this many nodes we stop trying to prettify and emit a code block.
MAX_NODES = 5000


def _escape_cell(value: Any) -> str:
    text = _scalar_to_text(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _scalar_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return str(value)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _count_nodes(value: Any, budget: int = MAX_NODES) -> int:
    """Cheap size estimate that stops as soon as the budget is blown."""
    stack = [value]
    seen = 0
    while stack and seen <= budget:
        current = stack.pop()
        seen += 1
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return seen


def _as_record_table(items: list[Any]) -> str | None:
    """Render a list of uniform flat objects as a Markdown table."""
    if len(items) < MIN_TABLE_ROWS or not all(isinstance(i, dict) for i in items):
        return None

    columns: list[str] = []
    for item in items:
        for key in item:
            if key not in columns:
                columns.append(key)
    if not columns or len(columns) > MAX_TABLE_COLUMNS:
        return None

    # Every value must be scalar, otherwise a table would lose information.
    if not all(_is_scalar(item.get(col)) for item in items for col in columns):
        return None

    header = "| " + " | ".join(_escape_cell(c) for c in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(_escape_cell(item.get(col)) for col in columns) + " |"
        for item in items
    ]
    return "\n".join([header, divider, *rows])


def _code_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, indent=2, ensure_ascii=False) + "\n```"


def _humanize(key: str) -> str:
    """snake_case / camelCase keys read better as prose headings."""
    text = key.replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else key


def _render(value: Any, depth: int, lines: list[str]) -> None:
    if isinstance(value, dict):
        _render_dict(value, depth, lines)
    elif isinstance(value, list):
        _render_list(value, depth, lines)
    else:
        lines.append(_scalar_to_text(value))


def _render_dict(obj: dict[str, Any], depth: int, lines: list[str]) -> None:
    if not obj:
        lines.append("_(empty)_")
        return

    scalars = {k: v for k, v in obj.items() if _is_scalar(v)}
    complex_items = {k: v for k, v in obj.items() if not _is_scalar(v)}

    for key, value in scalars.items():
        text = _scalar_to_text(value)
        lines.append(f"- **{key}**: {text}" if text else f"- **{key}**: _(empty)_")
    if scalars and complex_items:
        lines.append("")

    for key, value in complex_items.items():
        if depth < MAX_HEADING_DEPTH:
            lines.append(f"{'#' * (depth + 1)} {_humanize(key)}")
            lines.append("")
            _render(value, depth + 1, lines)
            lines.append("")
        else:
            lines.append(f"- **{key}**:")
            lines.append("")
            lines.append(_code_block(value))
            lines.append("")


def _render_list(items: list[Any], depth: int, lines: list[str]) -> None:
    if not items:
        lines.append("_(empty list)_")
        return

    table = _as_record_table(items)
    if table:
        lines.append(table)
        return

    if all(_is_scalar(i) for i in items):
        lines.extend(f"- {_scalar_to_text(i)}" for i in items)
        return

    for index, item in enumerate(items, start=1):
        if depth < MAX_HEADING_DEPTH:
            lines.append(f"{'#' * (depth + 1)} Item {index}")
            lines.append("")
            _render(item, depth + 1, lines)
            lines.append("")
        else:
            lines.append(_code_block(item))
            lines.append("")


def json_to_markdown(data: Any, *, title: str | None = None) -> str:
    """Convert already-parsed JSON into Markdown."""
    lines: list[str] = []
    if title:
        lines.extend([f"# {title}", ""])

    if _count_nodes(data) > MAX_NODES:
        # Large machine-generated payloads are more useful verbatim.
        lines.append(_code_block(data))
    else:
        _render(data, depth=1 if title else 0, lines=lines)

    return "\n".join(lines).strip() + "\n"


class JsonConverter(DocumentConverter):
    """Structure-aware JSON to Markdown converter."""

    def accepts(
        self, file_stream: BinaryIO, stream_info: StreamInfo, **kwargs: Any
    ) -> bool:
        extension = (stream_info.extension or "").lower()
        mimetype = (stream_info.mimetype or "").lower()
        if extension in ACCEPTED_EXTENSIONS:
            return True
        # .ipynb is also application/json but has its own converter.
        if extension:
            return False
        return any(mimetype.startswith(p) for p in ACCEPTED_MIME_PREFIXES)

    def convert(
        self, file_stream: BinaryIO, stream_info: StreamInfo, **kwargs: Any
    ) -> DocumentConverterResult:
        charset = stream_info.charset or "utf-8"
        raw = file_stream.read().decode(charset, errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Detection already validated this; if we still cannot parse, the
            # faithful thing is to hand back the source unchanged.
            return DocumentConverterResult(markdown=f"```json\n{raw.strip()}\n```\n")

        title = None
        if isinstance(data, dict):
            for key in ("title", "name", "Title", "Name"):
                if isinstance(data.get(key), str) and data[key].strip():
                    title = data[key].strip()
                    # Promoted to the heading, so don't repeat it as a bullet.
                    data = {k: v for k, v in data.items() if k != key}
                    break

        return DocumentConverterResult(
            markdown=json_to_markdown(data, title=title), title=title
        )
