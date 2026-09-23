from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.ingestion.parser import ParsedBlock, ParsedDocument

CAPTION_PATTERN = re.compile(r"(?i)^(figure|table|fig\.?|tab\.?|图|表)\s*\d*")
FORMULA_PATTERN = re.compile(r"\\[a-z]+|[\u2211\u222b\u221a\u00b1]|\^\{|_\{")
AFFILIATION_PATTERN = re.compile(
    r"(?i)(university|institute|college|laborator|inc\.|ltd\.|gmbh|school of|大学|学院|研究所)"
)


@dataclass(slots=True)
class ChunkDraft:
    ordinal: int
    content: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    content_hash: str
    section_title: str = ""
    chunk_type: str = "paragraph"


@dataclass(slots=True)
class SectionDraft:
    ordinal: int
    title: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None


def infer_chunk_type(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return "paragraph"
    if CAPTION_PATTERN.match(stripped):
        return "figure_caption"
    lines = [line for line in stripped.splitlines() if line.strip()]
    table_lines = sum(1 for line in lines if line.count("|") >= 2)
    if table_lines >= 2 and table_lines >= len(lines) / 2:
        return "table"
    if FORMULA_PATTERN.search(stripped) and len(stripped) <= 400:
        return "formula"
    return "paragraph"


def blocks_for_range(blocks: list[ParsedBlock], start: int, end: int) -> list[ParsedBlock]:
    return [block for block in blocks if block.char_end > start and block.char_start < end]


def _pages_for(parsed: ParsedDocument, start: int, end: int) -> tuple[int | None, int | None]:
    pages = [
        page.page_number for page in parsed.pages if page.char_end > start and page.char_start < end
    ]
    return (min(pages) if pages else None, max(pages) if pages else None)


MAX_SECTIONS = 64
MIN_SECTION_CHARS = 200

MARKDOWN_HEADING = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
NUMBERED_HEADING = re.compile(r"(?m)^(\d+(?:\.\d+){0,3})[.、]?\s+([^\n]{1,64})$")


def _is_heading(title: str) -> bool:
    if not title or len(title) > 64:
        return False
    if title[-1] in ".。;；,，:：":
        return False
    if title.lower().startswith(("http://", "https://", "www.")):
        return False
    if CAPTION_PATTERN.match(title) or AFFILIATION_PATTERN.search(title):
        return False
    first = title[0]
    return first.isupper() or "\u4e00" <= first <= "\u9fff"


def _build_sections(
    parsed: ParsedDocument, candidates: list[tuple[int, str]]
) -> list[SectionDraft]:
    text = parsed.text
    sections: list[SectionDraft] = []
    if candidates and candidates[0][0] > 0:
        page_start, page_end = _pages_for(parsed, 0, candidates[0][0])
        sections.append(SectionDraft(0, "前言", 0, candidates[0][0], page_start, page_end))
    for index, (start, title) in enumerate(candidates):
        end = candidates[index + 1][0] if index + 1 < len(candidates) else len(text)
        if end <= start:
            continue
        page_start, page_end = _pages_for(parsed, start, end)
        sections.append(SectionDraft(len(sections), title, start, end, page_start, page_end))
    merge_tiny = len(sections) > 8
    merged: list[SectionDraft] = []
    for section in sections:
        if (
            merge_tiny
            and merged
            and (section.char_end - section.char_start) < MIN_SECTION_CHARS
        ):
            previous = merged[-1]
            merged[-1] = SectionDraft(
                previous.ordinal,
                previous.title,
                previous.char_start,
                section.char_end,
                previous.page_start,
                section.page_end,
            )
        else:
            merged.append(section)
    return [
        SectionDraft(
            index,
            item.title,
            item.char_start,
            item.char_end,
            item.page_start,
            item.page_end,
        )
        for index, item in enumerate(merged)
    ]


def detect_sections(parsed: ParsedDocument) -> list[SectionDraft]:
    text = parsed.text
    markdown = [
        (match.start(), match.group(1).strip())
        for match in MARKDOWN_HEADING.finditer(text)
        if _is_heading(match.group(1).strip())
    ]
    if markdown:
        return _build_sections(parsed, markdown)
    numbered = [
        (match.start(), match.group(2).strip())
        for match in NUMBERED_HEADING.finditer(text)
        if _is_heading(match.group(2).strip())
    ]
    if len(numbered) > MAX_SECTIONS:
        page_start, page_end = _pages_for(parsed, 0, len(text))
        return [SectionDraft(0, "正文", 0, len(text), page_start, page_end)]
    if not numbered:
        page_start, page_end = _pages_for(parsed, 0, len(text))
        return [SectionDraft(0, "正文", 0, len(text), page_start, page_end)]
    return _build_sections(parsed, numbered)


def _split_section(
    parsed: ParsedDocument,
    section: SectionDraft,
    ordinal: int,
    max_chars: int,
    overlap_chars: int,
) -> list[ChunkDraft]:
    text = parsed.text[section.char_start : section.char_end]
    chunks: list[ChunkDraft] = []
    local_start = 0
    while local_start < len(text):
        hard_end = min(len(text), local_start + max_chars)
        end = hard_end
        if hard_end < len(text):
            boundary = max(
                text.rfind("\n\n", local_start + max_chars // 2, hard_end),
                text.rfind("。", local_start + max_chars // 2, hard_end),
            )
            if boundary > local_start:
                end = boundary + 1
        content = text[local_start:end]
        char_start = section.char_start + local_start
        char_end = section.char_start + end
        page_start, page_end = _pages_for(parsed, char_start, char_end)
        chunks.append(
            ChunkDraft(
                ordinal=ordinal + len(chunks),
                content=content,
                char_start=char_start,
                char_end=char_end,
                page_start=page_start,
                page_end=page_end,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                section_title=section.title,
                chunk_type=infer_chunk_type(content),
            )
        )
        if end >= len(text):
            break
        local_start = max(local_start + 1, end - overlap_chars)
    return chunks


def chunk_document(
    parsed: ParsedDocument, max_chars: int = 4000, overlap_chars: int = 300
) -> list[ChunkDraft]:
    if max_chars <= overlap_chars:
        raise ValueError("max_chars must be larger than overlap_chars")
    sections = detect_sections(parsed)
    chunks: list[ChunkDraft] = []
    for section in sections:
        chunks.extend(_split_section(parsed, section, len(chunks), max_chars, overlap_chars))
    return [
        ChunkDraft(
            ordinal=index,
            content=chunk.content,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            content_hash=chunk.content_hash,
            section_title=chunk.section_title,
            chunk_type=chunk.chunk_type,
        )
        for index, chunk in enumerate(chunks)
    ]
