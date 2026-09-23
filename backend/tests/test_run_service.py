from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.run_service import create_agent_run
from app.models import AgentRun, Message


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4().hex  # type: ignore[attr-defined]

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj: object) -> None:
        return None

    async def scalar(self, _statement: object) -> int:
        return 1


@pytest.mark.asyncio
async def test_create_agent_run_creates_message_and_run() -> None:
    db = FakeDb()
    user = SimpleNamespace(id="user-1", approval_mode="confirm")
    conversation = SimpleNamespace(id="conv-1", title="研究对话", notebook_id="nb-1")

    run = await create_agent_run(
        db,
        user=user,
        conversation=conversation,
        query="比较两篇论文的方法",
        attachment_ids=["doc-1"],
        attachment_instructions={"doc-1": "结合当前问题处理全文"},
        approval_mode=None,
    )

    messages = [item for item in db.added if isinstance(item, Message)]
    runs = [item for item in db.added if isinstance(item, AgentRun)]
    assert len(messages) == 1
    assert len(runs) == 1
    assert run.state["approval_mode"] == "confirm"
    assert run.state["input_message_id"] == messages[0].id
    assert conversation.title == "比较两篇论文的方法"
    assert run.notebook_id == "nb-1"
    assert run.attachment_ids == ["doc-1"]
    assert db.commits == 1


@pytest.mark.asyncio
async def test_create_agent_run_honours_explicit_approval_mode() -> None:
    db = FakeDb()
    user = SimpleNamespace(id="user-1", approval_mode="confirm")
    conversation = SimpleNamespace(id="conv-1", title="研究对话", notebook_id="nb-1")

    run = await create_agent_run(
        db,
        user=user,
        conversation=conversation,
        query="问题",
        approval_mode="read_only",
    )
    assert run.state["approval_mode"] == "read_only"
