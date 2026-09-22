from __future__ import annotations

import pytest

from app.retrieval.service import RetrievalService
from app.retrieval.types import SearchHit


class FakeResult:
    def all(self):
        return []


class FakeDb:
    async def execute(self, _statement):
        return FakeResult()


class FakeMilvus:
    def __init__(self, docs, chunks):
        self.docs = docs
        self.chunks = chunks

    def search_documents(self, query, vector, notebook_id, document_ids, limit):
        return list(self.docs)

    def hybrid_search(self, query, vector, notebook_id, document_ids, section_ids, limit):
        return list(self.chunks)


class FakeNeo4j:
    async def verify(self):
        return False


class FakeSiliconFlow:
    async def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def rerank(self, query, documents, top_n):
        return [
            {"index": index, "relevance_score": 1.0 - index * 0.1}
            for index in range(min(top_n, len(documents)))
        ]


def hit(chunk_id: str) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        text=f"content {chunk_id}",
        score=1.0,
        document_id="doc-1",
        document_version_id="version-1",
        title="Paper",
        section_id="sec-1",
    )


def service(docs, chunks) -> RetrievalService:
    return RetrievalService(FakeMilvus(docs, chunks), FakeNeo4j(), FakeSiliconFlow())


@pytest.mark.asyncio
async def test_layered_mode_uses_document_layer() -> None:
    docs = [{"entity": {"document_id": "doc-1"}}]
    result = await service(docs, [hit("c1"), hit("c2")]).search(
        FakeDb(), notebook_id="nb", query="q", document_ids=None, mode="layered"
    )
    assert result["layered_used"] is True
    assert result["mode_used"] == "layered"
    assert [item["chunk_id"] for item in result["items"]]


@pytest.mark.asyncio
async def test_layered_degrades_when_no_document_profiles() -> None:
    result = await service([], [hit("c1")]).search(
        FakeDb(), notebook_id="nb", query="q", document_ids=None, mode="layered"
    )
    assert result["layered_used"] is False
    assert result["layered_degraded"] is True
    assert result["mode_used"] == "hybrid"


@pytest.mark.asyncio
async def test_auto_uses_layered_when_profiles_exist() -> None:
    docs = [{"entity": {"document_id": "doc-1"}}]
    result = await service(docs, [hit("c1")]).search(
        FakeDb(), notebook_id="nb", query="帮我总结", document_ids=None, mode="auto"
    )
    assert result["layered_used"] is True
