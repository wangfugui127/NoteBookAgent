from __future__ import annotations

import pytest

from app.ingestion.graph_extract import extract_graph, extract_graph_batch
from app.providers.deepseek import ProviderResponse


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content

    async def invoke(self, messages, tools, _cb=None):
        return ProviderResponse(content=self.content)


@pytest.mark.asyncio
async def test_string_entities_are_normalized_without_crashing() -> None:
    provider = FakeProvider('{"entities": ["BERT", "RAG"], "relations": []}')
    entities, relations = await extract_graph("text", provider, "m")
    assert [item["key"] for item in entities] == ["bert", "rag"]
    assert relations == []


@pytest.mark.asyncio
async def test_invalid_json_falls_back_without_raising() -> None:
    entities, relations = await extract_graph("Some BERT model text", FakeProvider("not json"), "m")
    assert isinstance(entities, list)
    assert isinstance(relations, list)


@pytest.mark.asyncio
async def test_valid_objects_are_parsed() -> None:
    provider = FakeProvider(
        '{"entities":[{"key":"bert","name":"BERT","kind":"Method"}],'
        '"relations":[{"source":"bert","target":"bert","kind":"RELATED_TO","confidence":0.5}]}'
    )
    entities, relations = await extract_graph("text", provider, "m")
    assert entities[0]["key"] == "bert"
    assert relations[0]["kind"] == "RELATED_TO"


@pytest.mark.asyncio
async def test_batch_falls_back_when_response_is_not_a_list() -> None:
    provider = FakeProvider('{"entities": [], "relations": []}')
    results = await extract_graph_batch(["a BERT text", "another RAG text"], provider, "m")
    assert len(results) == 2
    assert all(isinstance(entities, list) for entities, _ in results)
