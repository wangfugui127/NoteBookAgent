from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, Conversation, Message, User


async def create_agent_run(
    db: AsyncSession,
    *,
    user: User,
    conversation: Conversation,
    query: str,
    attachment_ids: list[str] | None = None,
    attachment_instructions: dict[str, str] | None = None,
    approval_mode: str | None = None,
) -> AgentRun:
    """Create an AgentRun for a conversation. Caller decides whether to enqueue it.

    Shared by the interactive API and the evaluation service so both produce
    identical runs.
    """
    attachment_ids = list(attachment_ids or [])
    attachment_instructions = dict(attachment_instructions or {})
    input_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=query,
        attachments=[
            {
                "document_id": value,
                "instruction": attachment_instructions.get(value, ""),
            }
            for value in attachment_ids
        ],
    )
    db.add(input_message)
    await db.flush()
    message_count = await db.scalar(
        select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
    )
    if (message_count or 0) <= 1 and (conversation.title or "").strip() in {
        "",
        "New conversation",
        "研究对话",
    }:
        conversation.title = query.strip()[:30] or conversation.title
    resolved_mode = approval_mode or user.approval_mode or "confirm"
    run = AgentRun(
        conversation_id=conversation.id,
        user_id=user.id,
        notebook_id=conversation.notebook_id,
        query=query,
        attachment_ids=attachment_ids,
        state={
            "attachment_instructions": attachment_instructions,
            "input_message_id": input_message.id,
            "approval_mode": resolved_mode,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run
