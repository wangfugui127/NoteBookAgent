import json
from types import SimpleNamespace

import pytest

from app.agent.runtime import AgentRuntime
from app.agent.types import AgentState, ToolObservation


class FakeDb:
    def __init__(self) -> None:
        self.records: dict[str, SimpleNamespace] = {}

    async def get(self, _model, key):
        return self.records.get(key)


class FakeRegistry:
    @staticmethod
    def requires_approval(_name: str) -> bool:
        return False

    @staticmethod
    def decide(_name: str, _mode: str) -> str:
        return "allow"

    async def dispatch(self, name, arguments, _context):
        return ToolObservation(True, name, {"arguments": arguments})


class FakeEvents:
    async def emit(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_every_provider_tool_call_receives_a_tool_result() -> None:
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.registry = FakeRegistry()
    runtime.events = FakeEvents()

    async def ignore_evidence(*_args, **_kwargs):
        return None

    runtime._persist_observation_evidence = ignore_evidence
    db = FakeDb()
    entries = []
    for index in range(5):
        record_id = f"record-{index}"
        db.records[record_id] = SimpleNamespace(status="pending", result=None)
        entries.append(
            {
                "tool_call_id": record_id,
                "provider_call_id": f"call-{index}",
                "name": "search_notebook",
                "arguments": {"index": index},
                "risk": "read",
                "executable": index < 3,
            }
        )
    messages = []
    paused = await runtime._process_tool_batch(
        db,
        SimpleNamespace(id="run", state={}),
        AgentState("run", "notebook", "user"),
        messages,
        SimpleNamespace(),
        entries,
        ["search_notebook"],
    )
    assert not paused
    assert [item["tool_call_id"] for item in messages] == [f"call-{i}" for i in range(5)]
    assert db.records["record-3"].result["error_code"] == "tool_call_limit_exceeded"


class DenyRegistry:
    @staticmethod
    def decide(_name: str, _mode: str) -> str:
        return "deny"

    async def dispatch(self, *_args, **_kwargs):
        raise AssertionError("denied tool must not be dispatched")


@pytest.mark.asyncio
async def test_read_only_denies_write_without_dispatch() -> None:
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.registry = DenyRegistry()
    runtime.events = FakeEvents()

    async def ignore_evidence(*_args, **_kwargs):
        return None

    runtime._persist_observation_evidence = ignore_evidence
    db = FakeDb()
    db.records["r1"] = SimpleNamespace(status="pending", result=None)
    entries = [
        {
            "tool_call_id": "r1",
            "provider_call_id": "c1",
            "name": "add_paper_to_notebook",
            "arguments": {},
            "risk": "write",
            "executable": True,
        }
    ]
    messages: list[dict] = []
    paused = await runtime._process_tool_batch(
        db,
        SimpleNamespace(id="run", state={"approval_mode": "read_only"}),
        AgentState("run", "notebook", "user"),
        messages,
        SimpleNamespace(),
        entries,
        ["add_paper_to_notebook"],
    )
    assert not paused
    assert json.loads(messages[0]["content"])["error_code"] == "permission_denied"
    assert db.records["r1"].status == "rejected"
