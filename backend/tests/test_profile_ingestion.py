from __future__ import annotations

import pytest

from app.ingestion.profile import build_document_profile, extract_abstract, extract_keywords
from app.providers.deepseek import ProviderResponse

TEXT = """# Abstract
This paper studies wildfire detection and reports a clear improvement.

Keywords: remote sensing; wildfire; change detection

# 1. Introduction
Body text here.
"""


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content

    async def invoke(self, messages, tools, _cb=None):
        return ProviderResponse(content=self.content)


def test_deterministic_abstract_and_keywords() -> None:
    assert extract_abstract(TEXT).startswith("This paper studies")
    assert extract_keywords(TEXT) == ["remote sensing", "wildfire", "change detection"]


@pytest.mark.asyncio
async def test_profile_without_provider_is_heuristic() -> None:
    profile = await build_document_profile(
        title="Wildfire Paper",
        full_text=TEXT,
        section_titles=["Abstract", "Introduction"],
        provider=None,
        model_name="deepseek-flash",
    )
    assert profile["abstract_source"] == "original"
    assert profile["extractor_model"] == "heuristic"
    assert "Wildfire Paper" in profile["profile_text"]
    assert "remote sensing" in profile["profile_text"]


@pytest.mark.asyncio
async def test_profile_generates_abstract_when_missing() -> None:
    provider = FakeProvider(
        """
```json
{"one_sentence":"s","data_and_method":"d","results_conclusion":"r",
 "contribution_limitations":"c","keywords":["k1"],"region":"中国",
 "time_range":"2020-2023","authors":["A","B"],"year":2023,
 "abstract":"generated abstract"}
```
"""
    )
    profile = await build_document_profile(
        title="No Abstract",
        full_text="# 1. Intro\n正文内容，没有摘要标题。",
        section_titles=["Intro"],
        provider=provider,
        model_name="deepseek-flash",
    )
    assert profile["abstract_source"] == "generated"
    assert profile["abstract"] == "generated abstract"
    assert profile["year"] == 2023
    assert profile["region"] == "中国"
    assert profile["one_sentence"] == "s"
    assert profile["extractor_model"] == "deepseek-flash"
