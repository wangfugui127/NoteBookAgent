from __future__ import annotations

from app.agent.messages import (
    TOOL_RESULT_PLACEHOLDER,
    clear_old_tool_results,
    sanitize_messages,
    trim_history_by_turns,
)


def conversation() -> list[dict]:
    return [
        {"role": "user", "content": "q1"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "a1", "type": "function", "function": {"name": "t"}}],
        },
        {"role": "tool", "tool_call_id": "a1", "content": "r1"},
        {"role": "assistant", "content": "ans1"},
        {"role": "user", "content": "q2"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "b1", "type": "function", "function": {"name": "t"}},
                {"id": "b2", "type": "function", "function": {"name": "t"}},
            ],
        },
        {"role": "tool", "tool_call_id": "b1", "content": "r2"},
        {"role": "assistant", "content": "ans2"},
    ]


def test_sanitize_drops_orphan_tool() -> None:
    assert sanitize_messages([{"role": "tool", "tool_call_id": "z", "content": "x"}]) == []


def test_sanitize_fills_missing_tool_response() -> None:
    result = sanitize_messages(conversation())
    ids = [item.get("tool_call_id") for item in result if item.get("role") == "tool"]
    assert ids == ["a1", "b1", "b2"]


def test_trim_history_by_turns_keeps_complete_pairing() -> None:
    result = trim_history_by_turns(conversation(), 1)
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "q2"
    roles = [item["role"] for item in result]
    assert roles.count("user") == 1
    assert result[-1] == {"role": "assistant", "content": "ans2"}


def test_clear_old_tool_results_keeps_recent_verbatim() -> None:
    cleared, changed = clear_old_tool_results(conversation(), keep_recent=1)
    assert changed is True
    tool_messages = [item for item in cleared if item.get("role") == "tool"]
    assert tool_messages[0]["content"] == TOOL_RESULT_PLACEHOLDER
    assert tool_messages[-1]["content"] == "r2"
