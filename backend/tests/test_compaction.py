from __future__ import annotations

from typing import Any

import pytest

from app.agent.compactor import SUMMARY_PREFIX, ContextCompactor
from app.core.config import Settings
from app.providers.deepseek import ProviderResponse


class FakeProvider:
    def __init__(self, content: str = "结构化摘要", fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.calls = 0

    async def invoke(self, messages: list[dict[str, Any]], tools: list[Any], _cb: Any = None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        return ProviderResponse(content=self.content)


def settings() -> Settings:
    return Settings(
        model_context_window=2_000,
        max_output_tokens=100,
        context_safety_ratio=0.95,
        context_trim_threshold=0.6,
        context_summary_threshold=0.75,
        context_keep_recent_turns=2,
    )


def turn(index: int, size: int = 400) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": f"问题{index}:" + "中" * size},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call-{index}",
                    "type": "function",
                    "function": {"name": "search_notebook", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": f"call-{index}", "content": "工具结果" + "文" * size},
        {"role": "assistant", "content": f"回答{index}"},
    ]


def messages(turns: int, size: int = 400) -> list[dict[str, Any]]:
    system = [{"role": "system", "content": "ROOT PROMPT"}]
    convo = [item for index in range(turns) for item in turn(index, size)]
    return [*system, *convo]


@pytest.mark.asyncio
async def test_small_context_is_untouched() -> None:
    compactor = ContextCompactor(settings(), FakeProvider())
    original = messages(1, 10)
    result, omissions, summary = await compactor.compact(original)
    assert result == original
    assert omissions == []
    assert summary is None


@pytest.mark.asyncio
async def test_tag1_drops_old_turns_and_keeps_recent() -> None:
    provider = FakeProvider()
    compactor = ContextCompactor(settings(), provider)
    result, omissions, _ = await compactor.compact(messages(6))
    user_turns = [item for item in result if item.get("role") == "user"]
    assert len(user_turns) <= 2
    assert any(item.get("role") == "system" for item in result)
    assert omissions


@pytest.mark.asyncio
async def test_tag2_summarizes_older_turns_with_provider() -> None:
    provider = FakeProvider(content="目标：研究\n关键证据：[evidence:abc]")
    compactor = ContextCompactor(settings(), provider)
    result, omissions, summary = await compactor.compact(messages(6, size=2_000))
    assert provider.calls >= 1
    assert summary is not None
    assert any(
        str(item.get("content", "")).startswith(SUMMARY_PREFIX) for item in result
    )
    assert "[evidence:abc]" in str(result)


@pytest.mark.asyncio
async def test_provider_failure_keeps_messages_and_does_not_raise() -> None:
    compactor = ContextCompactor(settings(), FakeProvider(fail=True))
    result, omissions, summary = await compactor.compact(messages(6, size=2_000))
    assert summary is None
    assert not any(str(item.get("content", "")).startswith(SUMMARY_PREFIX) for item in result)
    assert omissions


@pytest.mark.asyncio
async def test_current_user_input_is_never_dropped() -> None:
    compactor = ContextCompactor(settings(), FakeProvider())
    data = messages(6)
    result, _, _ = await compactor.compact(data)
    assert result[-1]["content"] == "回答5"
    assert any(str(item.get("content") or "").startswith("问题5") for item in result)
