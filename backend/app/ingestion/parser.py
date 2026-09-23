from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

PARSER_NAME = "layout-markdown"
PARSER_VERSION = "1"

BLOCK_HEADING = "heading"
BLOCK_PARAGRAPH = "paragraph"
BLOCK_TABLE = "table"
BLOCK_FORMULA = "formula"
BLOCK_FIGURE_CAPTION = "figure_caption"

CHUNK_TYPES = {"paragraph", "table", "formula", "figure_caption"}

HEADING_MARKDOWN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
NUMBERED_HEADING_LINE = re.compile(r"^(\d+(?:\.\d+){0,3})[.、]?\s+(\S.{0,79})$")
CAPTION_PATTERN = re.compile(r"(?i)^(figure|table|fig\.?|tab\.?|图|表)\s*\d*")
AFFILIATION_PATTERN = re.compile(
    r"(?i)(university|institute|college|laborator|inc\.|ltd\.|gmbh|school of|大学|学院|研究所)"
)
FORMULA_MARKERS = re.compile(r"\\[a-z]+|[\u2211\u222b\u221a\u00b1^]|_\{|\^\{")


@dataclass(slots=True)
class ParsedBlock:
    kind: str
    text: str
    markdown: str
    page_number: int
    level: int = 0
    char_start: int = 0
    char_end: int = 0
    bbox: list[float] = field(default_factory=list)


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    char_start: int
    char_end: int
    text: str


@dataclass(slots=True)
class ParsedDocument:
    text: str
    pages: list[ParsedPage]
    blocks: list[ParsedBlock] = field(default_factory=list)
    markdown: str = ""


def _line_text(line: dict[str, Any]) -> str:
    return "".join(str(span.get("text") or "") for span in line.get("spans") or [])


def _is_bold(span: dict[str, Any]) -> bool:
    try:
        if int(span.get("flags") or 0) & 16:
            return True
    except (TypeError, ValueError):
        pass
    return "bold" in str(span.get("font") or "").lower()


def _looks_like_formula(text: str) -> bool:
    if len(text) > 200 or "=" not in text:
        return False
    return bool(FORMULA_MARKERS.search(text))


def classify_block(text: str, size: float, body_size: float, bold: bool) -> tuple[str, int]:
    stripped = text.strip()
    if not stripped:
        return BLOCK_PARAGRAPH, 0
    if CAPTION_PATTERN.match(stripped):
        return BLOCK_FIGURE_CAPTION, 0
    if AFFILIATION_PATTERN.search(stripped):
        return BLOCK_PARAGRAPH, 0
    if _looks_like_formula(stripped):
        return BLOCK_FORMULA, 0
    too_long = len(stripped) > 100 or len(stripped.split()) > 16
    if too_long or stripped[-1] in ".。;；,，:：":
        return BLOCK_PARAGRAPH, 0
    numbered = bool(re.match(r"^\d+(?:\.\d+){0,3}[.、]?\s", stripped))
    ratio = size / max(body_size, 0.1)
    if ratio >= 1.5:
        return BLOCK_HEADING, 1
    if ratio >= 1.25:
        return BLOCK_HEADING, 2
    if ratio >= 1.1:
        return BLOCK_HEADING, 3
    if numbered:
        return BLOCK_HEADING, 4
    if bold and ratio >= 1.05 and len(stripped) <= 60:
        return BLOCK_HEADING, 4
    return BLOCK_PARAGRAPH, 0


def block_markdown(kind: str, text: str, level: int) -> str:
    if kind == BLOCK_HEADING:
        return f"{'#' * max(1, min(level or 1, 6))} {text}"
    if kind == BLOCK_FORMULA:
        return f"$$\n{text}\n$$"
    return text


def _table_to_markdown(rows: list[list[Any]]) -> str:
    cleaned: list[list[str]] = []
    width = 0
    for row in rows or []:
        cells = [re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row]
        if not any(cells):
            continue
        width = max(width, len(cells))
        cleaned.append(cells)
    if not cleaned or width == 0:
        return ""
    padded = [row + [""] * (width - len(row)) for row in cleaned]
    header, *body = padded
    if not any(header):
        header = [f"col{index + 1}" for index in range(width)]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _body_font_size(document: pymupdf.Document) -> float:
    counts: dict[float, int] = {}
    for index in range(document.page_count):
        data = document[index].get_text("dict")
        for block in data.get("blocks") or []:
            if block.get("type") != 0:
                continue
            for line in block.get("lines") or []:
                for span in line.get("spans") or []:
                    text = str(span.get("text") or "")
                    if not text.strip():
                        continue
                    size = round(float(span.get("size") or 10.0) * 2) / 2
                    counts[size] = counts.get(size, 0) + len(text)
    if not counts:
        return 10.0
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _bbox_center_inside(bbox: tuple[float, float, float, float], container: Any) -> bool:
    try:
        x0, y0, x1, y1 = bbox
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        cx0, cy0, cx1, cy1 = container
        return cx0 <= cx <= cx1 and cy0 <= cy <= cy1
    except (TypeError, ValueError):
        return False


def _page_tables(page: pymupdf.Page) -> list[tuple[Any, str]]:
    try:
        finder = page.find_tables()
    except Exception:
        return []
    tables: list[tuple[Any, str]] = []
    for table in finder.tables:
        try:
            markdown = _table_to_markdown(table.extract())
        except Exception:
            continue
        if markdown:
            tables.append((tuple(table.bbox), markdown))
    return tables


def _order_items(
    items: list[tuple[str, str, str, tuple[float, float, float, float], int]],
    page_width: float,
    page_height: float,
) -> list[tuple[str, str, str, tuple[float, float, float, float], int]]:
    if len(items) <= 1:
        return items
    midpoint = page_width / 2
    left = [item for item in items if item[3][0] < midpoint * 0.95]
    right = [item for item in items if item[3][0] >= midpoint * 0.95]
    if left and right:
        left_span = (min(i[3][1] for i in left), max(i[3][3] for i in left))
        right_span = (min(i[3][1] for i in right), max(i[3][3] for i in right))
        overlap = min(left_span[1], right_span[1]) - max(left_span[0], right_span[0])
        if overlap > 0.15 * max(page_height, 1):
            left.sort(key=lambda item: (item[3][1], item[3][0]))
            right.sort(key=lambda item: (item[3][1], item[3][0]))
            return [*left, *right]
    return sorted(items, key=lambda item: (item[3][1], item[3][0]))


def _parse_pdf(path: Path) -> ParsedDocument:
    document = pymupdf.open(path)
    try:
        body_size = _body_font_size(document)
        blocks: list[ParsedBlock] = []
        pages: list[ParsedPage] = []
        pieces: list[str] = []
        cursor = 0
        for index in range(document.page_count):
            page = document[index]
            page_number = index + 1
            tables = _page_tables(page)
            table_bboxes = [bbox for bbox, _ in tables]
            items: list[tuple[str, str, str, tuple[float, float, float, float], int]] = []
            data = page.get_text("dict")
            for block in data.get("blocks") or []:
                if block.get("type") != 0:
                    continue
                bbox = tuple(block.get("bbox") or (0.0, 0.0, 0.0, 0.0))
                if any(_bbox_center_inside(bbox, table_bbox) for table_bbox in table_bboxes):
                    continue
                lines = block.get("lines") or []
                text = "\n".join(_line_text(line) for line in lines).strip()
                if not text:
                    continue
                size = max(
                    (
                        float(span.get("size") or body_size)
                        for line in lines
                        for span in line.get("spans") or []
                    ),
                    default=body_size,
                )
                bold = any(_is_bold(span) for line in lines for span in line.get("spans") or [])
                kind, level = classify_block(text, size, body_size, bold)
                items.append((kind, text, block_markdown(kind, text, level), bbox, level))
            for bbox, markdown in tables:
                items.append((BLOCK_TABLE, markdown, markdown, bbox, 0))

            ordered = _order_items(items, float(page.rect.width), float(page.rect.height))
            parts: list[str] = []
            local_cursor = 0
            specs: list[tuple[str, str, str, int, int, int, tuple[float, float, float, float]]] = []
            for kind, text, markdown, bbox, level in ordered:
                if parts:
                    parts.append("\n\n")
                    local_cursor += 2
                start = local_cursor
                parts.append(markdown)
                local_cursor += len(markdown)
                specs.append((kind, text, markdown, level, start, local_cursor, bbox))
            page_markdown = "".join(parts)
            if not page_markdown.strip():
                continue
            if pieces:
                pieces.append("\n\n")
                cursor += 2
            page_start = cursor
            pieces.append(page_markdown)
            cursor += len(page_markdown)
            pages.append(ParsedPage(page_number, page_start, cursor, page_markdown))
            for kind, text, markdown, level, start, end, bbox in specs:
                blocks.append(
                    ParsedBlock(
                        kind=kind,
                        text=text,
                        markdown=markdown,
                        page_number=page_number,
                        level=level,
                        char_start=page_start + start,
                        char_end=page_start + end,
                        bbox=[float(value) for value in bbox],
                    )
                )
        text = "".join(pieces)
    finally:
        document.close()
    if len(text.strip()) < 50:
        raise ValueError("PDF has no usable text layer; OCR is required before ingestion")
    return ParsedDocument(text, pages, blocks, text)


def _heading_of(line: str) -> tuple[str, int] | None:
    stripped = line.strip()
    heading = HEADING_MARKDOWN.match(stripped)
    if heading:
        return heading.group(2).strip(), len(heading.group(1))
    numbered = NUMBERED_HEADING_LINE.match(stripped)
    if numbered:
        candidate = numbered.group(2).strip()
        if candidate and (candidate[0].isupper() or "\u4e00" <= candidate[0] <= "\u9fff"):
            return candidate, 4
    return None


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines) or "|" not in lines[index]:
        return False
    return bool(re.match(r"^\s*\|?[\s:|-]+\|", lines[index + 1]))


def parse_text_blocks(text: str) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    buffer: list[int] = []

    def flush() -> None:
        if not buffer:
            return
        start = offsets[buffer[0]]
        end = offsets[buffer[-1]] + len(lines[buffer[-1]])
        buffer.clear()
        content = text[start:end]
        if content.strip():
            blocks.append(
                ParsedBlock(
                    kind=BLOCK_PARAGRAPH,
                    text=content,
                    markdown=content.strip(),
                    page_number=1,
                    level=0,
                    char_start=start,
                    char_end=end,
                )
            )

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush()
            index += 1
            continue
        heading = _heading_of(line)
        if heading is not None:
            flush()
            title, level = heading
            markdown = block_markdown(BLOCK_HEADING, title, level)
            blocks.append(
                ParsedBlock(
                    BLOCK_HEADING,
                    title,
                    markdown,
                    1,
                    level,
                    offsets[index],
                    offsets[index] + len(line),
                )
            )
            index += 1
            continue
        if CAPTION_PATTERN.match(stripped):
            flush()
            markdown = block_markdown(BLOCK_FIGURE_CAPTION, stripped, 0)
            blocks.append(
                ParsedBlock(
                    BLOCK_FIGURE_CAPTION,
                    stripped,
                    markdown,
                    1,
                    0,
                    offsets[index],
                    offsets[index] + len(line),
                )
            )
            index += 1
            continue
        if _looks_like_formula(stripped):
            flush()
            markdown = block_markdown(BLOCK_FORMULA, stripped, 0)
            blocks.append(
                ParsedBlock(
                    BLOCK_FORMULA,
                    stripped,
                    markdown,
                    1,
                    0,
                    offsets[index],
                    offsets[index] + len(line),
                )
            )
            index += 1
            continue
        if _is_table_start(lines, index):
            flush()
            start_index = index
            while index < len(lines) and "|" in lines[index]:
                index += 1
            start = offsets[start_index]
            end = offsets[index - 1] + len(lines[index - 1])
            markdown = text[start:end].strip()
            blocks.append(
                ParsedBlock(BLOCK_TABLE, markdown, markdown, 1, 0, start, end)
            )
            continue
        buffer.append(index)
        index += 1
    flush()
    return blocks


def parse_document(path: Path, media_type: str) -> ParsedDocument:
    if media_type == "application/pdf" or path.suffix.lower() == ".pdf":
        return _parse_pdf(path)
    text_suffixes = {".txt", ".md", ".markdown"}
    if path.suffix.lower() not in text_suffixes:
        # Some multipart clients omit the original filename and send text as
        # application/octet-stream.  Accept it only when it is valid UTF-8;
        # arbitrary binary input must still fail closed.
        if media_type != "application/octet-stream":
            raise ValueError(f"unsupported document type: {media_type or path.suffix}")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"unsupported binary document: {media_type}") from exc
    else:
        text = path.read_text(encoding="utf-8-sig")
    return ParsedDocument(text, [ParsedPage(1, 0, len(text), text)], parse_text_blocks(text), text)
