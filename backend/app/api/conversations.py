from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, select

from app.api.dependencies import CurrentUser, DbSession
from app.models import (
    AgentRun,
    Citation,
    Conversation,
    ConversationResourceSelection,
    Document,
    Evidence,
    Message,
    Notebook,
    RunStatus,
)
from app.schemas import ConversationCreate, ResourceSelectionUpdate

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    notebook_id: str, db: DbSession, user: CurrentUser
) -> dict[str, object]:
    notebook = await db.scalar(
        select(Notebook).where(Notebook.id == notebook_id, Notebook.owner_id == user.id)
    )
    if not notebook:
        raise HTTPException(404, "notebook not found")
    rows = list(
        (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.notebook_id == notebook_id,
                    Conversation.user_id == user.id,
                )
                .order_by(Conversation.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {"id": item.id, "title": item.title, "updated_at": item.updated_at} for item in rows
        ]
    }


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: str, db: DbSession, user: CurrentUser
) -> dict[str, object]:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )
    if not conversation:
        raise HTTPException(404, "conversation not found")
    messages = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    items: list[dict[str, object]] = []
    for message in messages:
        citations = list(
            (
                await db.execute(
                    select(Citation, Evidence)
                    .join(Evidence, Citation.evidence_id == Evidence.id)
                    .where(Citation.message_id == message.id)
                )
            ).all()
        )
        items.append(
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "attachments": message.attachments,
                "created_at": message.created_at,
                "citations": [
                    {
                        "evidence_id": evidence.id,
                        "chunk_id": evidence.chunk_id,
                        "source_kind": evidence.source_kind,
                        "source_id": evidence.source_id,
                        "page_start": evidence.page_start,
                        "page_end": evidence.page_end,
                        "char_start": evidence.char_start,
                        "char_end": evidence.char_end,
                    }
                    for _, evidence in citations
                ],
            }
        )
    return {"items": items}


@router.post("", status_code=201)
async def create_conversation(
    payload: ConversationCreate, db: DbSession, user: CurrentUser
) -> dict[str, str]:
    notebook = await db.scalar(
        select(Notebook).where(Notebook.id == payload.notebook_id, Notebook.owner_id == user.id)
    )
    if not notebook:
        raise HTTPException(404, "notebook not found")
    conversation = Conversation(user_id=user.id, **payload.model_dump())
    db.add(conversation)
    await db.flush()
    document_ids = (
        (await db.execute(select(Document.id).where(Document.notebook_id == notebook.id)))
        .scalars()
        .all()
    )
    for document_id in document_ids:
        db.add(
            ConversationResourceSelection(
                conversation_id=conversation.id, document_id=document_id, mode="summary"
            )
        )
    await db.commit()
    return {"id": conversation.id}


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, db: DbSession, user: CurrentUser
) -> Response:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )
    if not conversation:
        raise HTTPException(404, "conversation not found")
    active_run = await db.scalar(
        select(AgentRun.id)
        .where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.status.in_(
                [RunStatus.pending, RunStatus.running, RunStatus.waiting_approval]
            ),
        )
        .limit(1)
    )
    if active_run:
        raise HTTPException(409, "对话正在运行，请先停止")
    await db.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await db.commit()
    return Response(status_code=204)


@router.put("/{conversation_id}/resources/{document_id}")
async def set_resource_mode(
    conversation_id: str,
    document_id: str,
    payload: ResourceSelectionUpdate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )
    if not conversation:
        raise HTTPException(404, "conversation not found")
    document = await db.scalar(
        select(Document).where(
            Document.id == document_id, Document.notebook_id == conversation.notebook_id
        )
    )
    if not document:
        raise HTTPException(404, "document not found")
    selection = await db.scalar(
        select(ConversationResourceSelection).where(
            ConversationResourceSelection.conversation_id == conversation_id,
            ConversationResourceSelection.document_id == document_id,
        )
    )
    if selection:
        selection.mode = payload.mode
    else:
        db.add(
            ConversationResourceSelection(
                conversation_id=conversation_id, document_id=document_id, mode=payload.mode
            )
        )
    await db.commit()
    return {"mode": payload.mode.value}
