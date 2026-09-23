from __future__ import annotations

import json

import pytest

from app.ingestion.graph_extract import (
    extract_graph,
    extract_graph_batch,
    extract_section_graph,
)
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


@pytest.mark.asyncio
async def test_section_graph_flattens_experiment_structure() -> None:
    payload = json.dumps(
        [
            {
                "index": 0,
                "experiments": [
                    {
                        "key": "rf-exp",
                        "name": "RF 实验",
                        "methods": [{"key": "rf", "name": "Random Forest"}],
                        "datasets": [{"key": "sentinel-2", "name": "Sentinel-2"}],
                        "results": [
                            {
                                "key": "f1-result",
                                "name": "F1=0.89",
                                "metric": {"key": "f1-metric", "name": "F1"},
                            }
                        ],
                    }
                ],
            }
        ]
    )
    results = await extract_section_graph("Results", ["段落到此"], FakeProvider(payload), "m")
    entities, relations = results[0]
    assert {entity["kind"] for entity in entities} == {
        "Experiment",
        "Method",
        "Dataset",
        "Result",
        "Metric",
    }
    assert {relation["kind"] for relation in relations} == {
        "USES_METHOD",
        "USES_DATASET",
        "REPORTS_RESULT",
        "MEASURES",
    }


@pytest.mark.asyncio
async def test_section_graph_without_provider_is_empty() -> None:
    results = await extract_section_graph("Methods", ["a", "b"], None, "m")
    assert results == [([], []), ([], [])]
