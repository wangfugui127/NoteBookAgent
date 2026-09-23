from dataclasses import dataclass, field


@dataclass
class SearchHit:
    chunk_id: str
    text: str
    score: float
    document_id: str
    document_version_id: str
    title: str
    page_start: int | None = None
    page_end: int | None = None
    section_id: str | None = None
    section_title: str | None = None
    ordinal: int | None = None
    chunk_type: str | None = None
    block_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
