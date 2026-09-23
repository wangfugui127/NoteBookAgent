from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.agent.run_service import create_agent_run
from app.agent.tasks import execute_agent_run_task
from app.api.dependencies import CurrentUser, DbSession
from app.core.database import SessionFactory
from app.models import AgentRun, ApprovalRequest, Conversation, RunEvent, RunStatus
from app.schemas import AgentRunCreate, AgentRunView, ApprovalResolve

router = APIRouter(tags=["agent"])


async def owned_run(db: DbSession, run_id: str, user_id: str) -> AgentRun:
    run = await db.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
    )
    if not run:
        raise HTTPException(404, "run not found")
    return run


@router.post("/agent/runs", response_model=AgentRunView, status_code=202)
async def create_run(payload: AgentRunCreate, db: DbSession, user: CurrentUser) -> AgentRun:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == payload.conversation_id, Conversation.user_id == user.id
        )
    )
    if not conversation:
        raise HTTPException(404, "conversation not found")
    run = await create_agent_run(
        db,
        user=user,
        conversation=conversation,
        query=payload.query,
        attachment_ids=payload.attachment_ids,
        attachment_instructions=payload.attachment_instructions,
        approval_mode=payload.approval_mode,
    )
    execute_agent_run_task.delay(run.id)
    return run


@router.get("/agent/runs/{run_id}", response_model=AgentRunView)
async def get_run(run_id: str, db: DbSession, user: CurrentUser) -> AgentRun:
    return await owned_run(db, run_id, user.id)


@router.get("/agent/runs/{run_id}/context-manifest")
async def get_context_manifest(run_id: str, db: DbSession, user: CurrentUser) -> dict[str, object]:
    run = await owned_run(db, run_id, user.id)
    return {"items": run.state.get("context_manifests", [])}


@router.get("/agent/runs/{run_id}/events")
async def stream_events(
    run_id: str, request: Request, db: DbSession, user: CurrentUser
) -> EventSourceResponse:
    await owned_run(db, run_id, user.id)
    last_event_id = int(
        request.headers.get("last-event-id") or request.query_params.get("after") or 0
    )

    async def generator():
        cursor = last_event_id
        while True:
            if await request.is_disconnected():
                return
            async with SessionFactory() as session:
                events = (
                    (
                        await session.execute(
                            select(RunEvent)
                            .where(RunEvent.run_id == run_id, RunEvent.sequence > cursor)
                            .order_by(RunEvent.sequence)
                        )
                    )
                    .scalars()
                    .all()
                )
                for event in events:
                    cursor = event.sequence
                    yield {
                        "id": str(event.sequence),
                        "event": event.event_type,
                        "data": json.dumps(event.payload, ensure_ascii=False, default=str),
                    }
                run = await session.get(AgentRun, run_id)
                if (
                    run
                    and run.status in {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}
                    and not events
                ):
                    return
            await asyncio.sleep(0.5)

    return EventSourceResponse(generator())


@router.post("/agent/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str, db: DbSession, user: CurrentUser) -> dict[str, str]:
    run = await owned_run(db, run_id, user.id)
    run.status = RunStatus.cancelled
    await db.commit()
    return {"status": "cancelled"}


@router.post("/agent/runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str, db: DbSession, user: CurrentUser) -> dict[str, str]:
    run = await owned_run(db, run_id, user.id)
    if run.status not in {RunStatus.failed, RunStatus.cancelled}:
        raise HTTPException(409, "only failed or cancelled runs can be retried")
    run.status = RunStatus.pending
    run.error_message = None
    await db.commit()
    execute_agent_run_task.delay(run.id)
    return {"status": "pending"}


@router.get("/agent/runs/{run_id}/approvals")
async def list_approvals(run_id: str, db: DbSession, user: CurrentUser) -> dict[str, object]:
    await owned_run(db, run_id, user.id)
    approvals = (
        (await db.execute(select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)))
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": item.id,
                "status": item.status,
                "reason": item.reason,
                "mode": item.mode,
                "tool_risk": item.tool_risk,
                "tool_call_id": item.tool_call_id,
            }
            for item in approvals
        ]
    }


@router.post("/agent/approvals/{approval_id}/resolve", status_code=202)
async def resolve_approval(
    approval_id: str, payload: ApprovalResolve, db: DbSession, user: CurrentUser
) -> dict[str, str]:
    approval = await db.scalar(
        select(ApprovalRequest)
        .join(AgentRun, ApprovalRequest.run_id == AgentRun.id)
        .where(ApprovalRequest.id == approval_id, AgentRun.user_id == user.id)
    )
    if not approval:
        raise HTTPException(404, "approval not found")
    if approval.status != "pending":
        raise HTTPException(409, "approval already resolved")
    approval.status = payload.decision
    approval.resolved_by = user.id
    await db.commit()
    execute_agent_run_task.delay(approval.run_id)
    return {"status": payload.decision}
