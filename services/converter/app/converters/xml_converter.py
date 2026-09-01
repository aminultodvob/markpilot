"""XML to Markdown.

MarkItDown routes generic .xml through the plain-text converter, so the raw
markup is echoed back. This converter preserves the document's *hierarchy*
without exposing angle-bracket noise:

* the root element becomes the document heading;
* container elements become nested headings while the tree is shallow;
* repeated sibling elements with the same tag and flat children become a table;
* leaf elements become ``- **tag**: value`` bullets;
* attributes are surfaced, since in XML they routinely carry real data.

Parsing uses ``defusedxml`` so entity-expansion and external-entity attacks
(billion laughs, XXE) are refused rather than processed.
"""

from __future__ import annotations

from typing import Any, BinaryIO
from xml.etree.ElementTree import Element

from markitdown import DocumentConverter, DocumentConverterResult, StreamInfo

ACCEPTED_EXTENSIONS = (".xml",)
ACCEPTED_MIME_PREFIXES = ("application/xml", "text/xml")

MAX_HEADING_DEPTH = 4
MIN_TABLE_ROWS = 2
MAX_TABLE_COLUMNS = 12


def _local_name(tag: str) -> str:
    """Drop the ``{namespace}`` prefix ElementTree prepends to tags."""
    return tag.rpartition("}")[2] if "}" in tag else tag


def _humanize(tag: str) -> str:
    text = _local_name(tag).replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else tag


def _text_of(element: Element) -> str:
    return (element.text or "").strip()


def _is_leaf(element: Element) -> bool:
    return len(element) == 0


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _attributes_line(element: Element) -> str | None:
    if not element.attrib:
        return None
    parts = [f"**{_local_name(k)}**: {v}" for k, v in element.attrib.items()]
    return " · ".join(parts)


def _as_table(elements: list[Element]) -> str | None:
    """Render uniform repeated siblings as a table."""
    if len(elements) < MIN_TABLE_ROWS:
        return None
    if any(not _is_leaf(child) for el in elements for child in el):
        return None

    columns: list[str] = []
    rows: list[dict[str, str]] = []
    for element in elements:
        row: dict[str, str] = {
            f"@{_local_name(k)}": v for k, v in element.attrib.items()
        }
        for child in element:
            row[_local_name(child.tag)] = _text_of(child)
        if not row:
            return None
        for key in row:
            if key not in columns:
                columns.append(key)
        rows.append(row)

    if not columns or len(columns) > MAX_TABLE_COLUMNS:
        return None

    header = "| " + " | ".join(_escape_cell(c) for c in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_escape_cell(row.get(col, "")) for col in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _group_children(element: Element) -> list[tuple[str, list[Element]]]:
    """Group consecutive children by tag, preserving document order."""
    groups: list[tuple[str, list[Element]]] = []
    for child in element:
        tag = _local_name(child.tag)
        if groups and groups[-1][0] == tag:
            groups[-1][1].append(child)
        else:
            groups.append((tag, [child]))
    return groups


def _render_element(element: Element, depth: int, lines: list[str]) -> None:
    attributes = _attributes_line(element)
    if attributes:
        lines.extend([attributes, ""])

    text = _text_of(element)
    if text:
        lines.extend([text, ""])

    for tag, group in _group_children(element):
        if len(group) >= MIN_TABLE_ROWS:
            table = _as_table(group)
            if table:
                if depth < MAX_HEADING_DEPTH:
                    lines.extend([f"{'#' * (depth + 1)} {_humanize(tag)}", ""])
                lines.extend([table, ""])
                continue

        for child in group:
            if _is_leaf(child) and not child.attrib:
                value = _text_of(child)
                lines.append(
                    f"- **{_local_name(child.tag)}**: {value}"
                    if value
                    else f"- **{_local_name(child.tag)}**"
                )
            elif depth < MAX_HEADING_DEPTH:
                lines.extend([f"{'#' * (depth + 1)} {_humanize(child.tag)}", ""])
                _render_element(child, depth + 1, lines)
                lines.append("")
            else:
                lines.append(f"- **{_local_name(child.tag)}**")
                nested: list[str] = []
                _render_element(child, depth + 1, nested)
                lines.extend(f"  {line}" if line else "" for line in nested)


def xml_to_markdown(root: Element) -> str:
    title = _humanize(root.tag)
    lines = [f"# {title}", ""]
    _render_element(root, depth=1, lines=lines)
    return "\n".join(lines).strip() + "\n"


class XmlConverter(DocumentConverter):
    """Hierarchy-preserving XML to Markdown converter."""

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
        from defusedxml.ElementTree import fromstring

        charset = stream_info.charset or "utf-8"
        raw = file_stream.read().decode(charset, errors="replace")
        try:
            root = fromstring(raw)
        except Exception:
            # Detection validated well-formedness; anything left is returned
            # verbatim rather than silently dropped.
            return DocumentConverterResult(markdown=f"```xml\n{raw.strip()}\n```\n")

        return DocumentConverterResult(
            markdown=xml_to_markdown(root), title=_humanize(root.tag)
        )
