from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf


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


def parse_document(path: Path, media_type: str) -> ParsedDocument:
    if media_type == "application/pdf" or path.suffix.lower() == ".pdf":
        document = pymupdf.open(path)
        pieces: list[str] = []
        pages: list[ParsedPage] = []
        cursor = 0
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            if pieces:
                pieces.append("\n\n")
                cursor += 2
            start = cursor
            pieces.append(text)
            cursor += len(text)
            pages.append(ParsedPage(index, start, cursor, text))
        full_text = "".join(pieces)
        if len(full_text.strip()) < 50:
            raise ValueError("PDF has no usable text layer; OCR is required before ingestion")
        return ParsedDocument(full_text, pages)
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
    return ParsedDocument(text, [ParsedPage(1, 0, len(text), text)])
