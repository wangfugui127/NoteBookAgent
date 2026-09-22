from pathlib import Path

from app.ingestion.chunker import chunk_document, detect_sections
from app.ingestion.parser import ParsedDocument, ParsedPage, parse_document


def test_chunker_covers_document_and_preserves_page_bounds() -> None:
    text = "A" * 3000 + "\n\n" + "B" * 3000
    parsed = ParsedDocument(
        text=text,
        pages=[
            ParsedPage(1, 0, 3000, text[:3000]),
            ParsedPage(2, 3002, len(text), text[3002:]),
        ],
    )
    chunks = chunk_document(parsed, max_chars=2000, overlap_chars=200)
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)
    assert {item.page_start for item in chunks} >= {1, 2}


def test_section_detection_covers_markdown_document() -> None:
    text = "# 引言\n内容一。\n\n## 方法\n内容二。"
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, 0, len(text), text)])
    sections = detect_sections(parsed)
    assert [item.title for item in sections] == ["引言", "方法"]
    assert sections[0].char_start == 0
    assert sections[-1].char_end == len(text)


def test_section_detection_rejects_affiliations_and_captions() -> None:
    text = (
        "1 Introduction\n"
        "Mila - Quebec AI Institute\n"
        "McGill University\n"
        "Figure 2: Presto learns to reconstruct channels.\n"
        "one is missing (for instance, relying on Sentinel-1)\n"
        "2 Method\n"
        "3 Results\n"
    )
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, 0, len(text), text)])
    titles = [item.title for item in detect_sections(parsed)]
    assert "McGill University" not in titles
    assert all(not title.startswith("Figure") for title in titles)
    assert len(titles) <= 64


def test_section_detection_caps_noisy_numbered_lines() -> None:
    text = "\n".join(f"{index} Heading Number {index}" for index in range(1, 400))
    parsed = ParsedDocument(text=text, pages=[ParsedPage(1, 0, len(text), text)])
    sections = detect_sections(parsed)
    assert len(sections) == 1
    assert sections[0].title == "正文"


def test_octet_stream_without_filename_accepts_utf8_text(tmp_path: Path) -> None:
    path = tmp_path / "v1"
    path.write_text("# 方法\n这是一个没有原始文件名的 Markdown 上传。", encoding="utf-8")
    parsed = parse_document(path, "application/octet-stream")
    assert parsed.text.startswith("# 方法")
    assert parsed.pages[0].char_end == len(parsed.text)
