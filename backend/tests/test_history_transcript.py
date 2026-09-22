from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.runtime import AgentRuntime


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def get(self, _model, _key):
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def test_cap_history_keeps_most_recent_within_budget() -> None:
    messages = [{"role": "user", "content": "中" * 400} for _ in range(3)]
    kept = AgentRuntime._cap_history(messages, 1_000)
    assert len(kept) < len(messages)
    assert kept == messages[len(messages) - len(kept) :]


@pytest.mark.asyncio
async def test_save_transcript_strips_system_and_appends_answer() -> None:
    runtime = AgentRuntime.__new__(AgentRuntime)
    db = FakeDb()
    run = SimpleNamespace(id="run-1", conversation_id="conv-1")
    messages = [
        {"role": "system", "content": "ROOT"},
        {"role": "user", "content": "问题"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "结果"},
    ]
    await runtime._save_transcript(db, run, messages, "最终回答")
    stored = db.added[0].messages
    assert all(item["role"] != "system" for item in stored)
    assert stored[-1] == {"role": "assistant", "content": "最终回答"}
    assert any(item["role"] == "tool" and item["tool_call_id"] == "c1" for item in stored)
