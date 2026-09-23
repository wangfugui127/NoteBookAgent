from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.run_service import create_agent_run
from app.evaluation.scorers import (
    DEFAULT_SCORE_CONFIG,
    METRIC_FIELDS,
    aggregate_metrics,
    match_titles,
    score_case,
)
from app.models import (
    AgentRun,
    Chunk,
    Citation,
    Conversation,
    Document,
    DocumentVersion,
    EvalCaseResult,
    EvalRun,
    Evidence,
    Message,
    RunStatus,
    ToolCall,
    User,
)

TERMINAL_EVAL_STATUSES = {"completed", "failed", "cancelled"}


async def _load_run(db: AsyncSession, eval_run_id: str) -> EvalRun:
    # populate_existing forces a DB round trip so cancellation from another
    # session is observed instead of a stale identity-mapped instance.
    return await db.get(EvalRun, eval_run_id, populate_existing=True)


def case_has_metrics(case: Any) -> bool:
    return any(bool(getattr(case, field, None)) for field in METRIC_FIELDS)


def dataset_has_metrics(cases: list[Any]) -> bool:
    return any(case_has_metrics(case) for case in cases)


async def notebook_source_titles(db: AsyncSession, notebook_id: str) -> list[str]:
    rows = (
        (await db.execute(select(Document.title).where(Document.notebook_id == notebook_id)))
        .scalars()
        .all()
    )
    return [str(title) for title in rows if title]


def missing_sources_for(cases: list[Any], titles: list[str]) -> list[dict[str, Any]]:
    """List expected source titles that do not match any document in the notebook."""
    report: list[dict[str, Any]] = []
    for case in cases:
        _, missing = match_titles(list(getattr(case, "expected_source_titles", None) or []), titles)
        if missing:
            report.append(
                {
                    "case_key": getattr(case, "case_key", ""),
                    "question": getattr(case, "question", ""),
                    "missing": missing,
                }
            )
    return report


async def create_run_snapshot(
    db: AsyncSession,
    *,
    user: User,
    notebook_id: str,
    dataset: Any,
    cases: list[Any],
    missing_map: dict[str, list[str]] | None = None,
    score_config: dict[str, float] | None = None,
) -> EvalRun:
    """Create an EvalRun and snapshot every case into a pending result row."""
    missing_map = missing_map or {}
    run = EvalRun(
        user_id=user.id,
        notebook_id=notebook_id,
        dataset_id=getattr(dataset, "id", None),
        dataset_name=getattr(dataset, "name", "") or "",
        status="pending",
        total_cases=len(cases),
        score_config=dict(score_config or DEFAULT_SCORE_CONFIG),
    )
    db.add(run)
    await db.flush()
    for index, case in enumerate(cases, start=1):
        db.add(
            EvalCaseResult(
                eval_run_id=run.id,
                case_key=getattr(case, "case_key", "") or f"case-{index}",
                ordinal=index,
                question=getattr(case, "question", ""),
                status="pending",
                expected_tools=list(getattr(case, "expected_tools", None) or []),
                expected_source_titles=list(getattr(case, "expected_source_titles", None) or []),
                missing_sources=list(missing_map.get(getattr(case, "case_key", ""), [])),
                required_keywords=list(getattr(case, "required_keywords", None) or []),
            )
        )
    await db.commit()
    await db.refresh(run)
    return run


async def _titles_for_versions(db: AsyncSession, version_ids: set[str]) -> set[str]:
    if not version_ids:
        return set()
    rows = (
        (
            await db.execute(
                select(Document.title)
                .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                .where(DocumentVersion.id.in_(list(version_ids)))
            )
        )
        .scalars()
        .all()
    )
    return {str(title) for title in rows if title}


async def _version_ids_for_rows(
    db: AsyncSession, rows: list[tuple[str | None, str | None]]
) -> set[str]:
    version_ids: set[str] = set()
    chunk_ids = [chunk_id for chunk_id, _ in rows if chunk_id]
    if chunk_ids:
        version_ids |= set(
            (
                await db.execute(
                    select(Chunk.document_version_id).where(Chunk.id.in_(chunk_ids))
                )
            )
            .scalars()
            .all()
        )
    for _, source_id in rows:
        if source_id:
            version_ids.add(source_id)
    return version_ids


async def collect_observation(
    db: AsyncSession, agent_run_id: str, conversation_id: str
) -> dict[str, Any]:
    run = await db.get(AgentRun, agent_run_id)
    answer = str((run.state or {}).get("final_answer") or "") if run else ""
    tools = sorted(
        set(
            (
                await db.execute(select(ToolCall.tool_name).where(ToolCall.run_id == agent_run_id))
            )
            .scalars()
            .all()
        )
    )
    evidence_rows = list(
        (
            await db.execute(
                select(Evidence.chunk_id, Evidence.source_id).where(
                    Evidence.run_id == agent_run_id
                )
            )
        ).all()
    )
    evidence_titles = await _titles_for_versions(
        db, await _version_ids_for_rows(db, evidence_rows)
    )
    citation_rows = list(
        (
            await db.execute(
                select(Evidence.chunk_id, Evidence.source_id)
                .join(Citation, Citation.evidence_id == Evidence.id)
                .join(Message, Message.id == Citation.message_id)
                .where(Message.conversation_id == conversation_id, Message.role == "assistant")
            )
        ).all()
    )
    citation_titles = await _titles_for_versions(
        db, await _version_ids_for_rows(db, citation_rows)
    )
    return {
        "answer": answer,
        "tools": tools,
        "evidence_titles": sorted(evidence_titles),
        "citation_titles": sorted(citation_titles),
        "run_status": str(run.status) if run else "failed",
        "agent_run_id": agent_run_id,
    }


def _apply_score(result: EvalCaseResult, observation: dict[str, Any], latency_ms: int) -> None:
    score = score_case(
        expected_tools=list(result.expected_tools or []),
        actual_tools=list(observation["tools"]),
        expected_source_titles=list(result.expected_source_titles or []),
        evidence_titles=list(observation["evidence_titles"]),
        citation_titles=list(observation["citation_titles"]),
        missing_sources=list(result.missing_sources or []),
        required_keywords=list(result.required_keywords or []),
        answer=observation["answer"],
        run_status=str(observation["run_status"]),
    )
    result.actual_tools = list(observation["tools"])
    result.answer = observation["answer"]
    result.agent_run_id = observation["agent_run_id"]
    result.latency_ms = latency_ms
    result.route_score = score.route_score
    result.retrieval_score = score.retrieval_score
    result.citation_score = score.citation_score
    result.keyword_score = score.keyword_score
    result.total_score = score.total_score
    result.passed = score.passed
    result.status = score.status
    result.matched_sources = score.matched_sources
    result.matched_keywords = score.detail.get("matched_keywords", [])
    result.detail = score.detail


async def execute_evaluation(db: AsyncSession, eval_run_id: str, runtime: Any) -> None:
    """Run every snapshotted case in order, updating progress after each one."""
    run = await _load_run(db, eval_run_id)
    if not run or run.status == "cancelled":
        return
    run.status = "running"
    await db.commit()
    try:
        results = (
            (
                await db.execute(
                    select(EvalCaseResult)
                    .where(EvalCaseResult.eval_run_id == eval_run_id)
                    .order_by(EvalCaseResult.ordinal)
                )
            )
            .scalars()
            .all()
        )
        for result in results:
            run = await _load_run(db, eval_run_id)
            if run.status == "cancelled":
                if result.status in {"pending", "running"}:
                    result.status = "cancelled"
                    await db.commit()
                continue
            run.current_case_key = result.case_key
            run.current_case_result_id = result.id
            result.status = "running"
            await db.commit()
            started = time.perf_counter()
            case_cancelled = False
            try:
                user = await db.get(User, run.user_id)
                conversation = Conversation(
                    user_id=run.user_id,
                    notebook_id=run.notebook_id,
                    title=(result.question or "eval")[:60],
                )
                db.add(conversation)
                await db.commit()
                await db.refresh(conversation)
                agent_run = await create_agent_run(
                    db,
                    user=user,
                    conversation=conversation,
                    query=result.question,
                    approval_mode="read_only",
                )
                run = await _load_run(db, eval_run_id)
                run.current_agent_run_id = agent_run.id
                await db.commit()
                await runtime.execute(db, agent_run.id)
                if (await _load_run(db, eval_run_id)).status == "cancelled":
                    case_cancelled = True
                    result.status = "cancelled"
                    result.passed = False
                    executed = await db.get(AgentRun, agent_run.id)
                    if executed:
                        executed.status = RunStatus.cancelled
                else:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    observation = await collect_observation(db, agent_run.id, conversation.id)
                    _apply_score(result, observation, latency_ms)
            except Exception as exc:  # noqa: BLE001 - one bad case must not abort the run
                await db.rollback()
                result = await db.get(EvalCaseResult, result.id)
                result.status = "error"
                result.passed = False
                result.error_message = str(exc)
            run = await _load_run(db, eval_run_id)
            if not case_cancelled:
                run.completed_cases += 1
                if result.passed:
                    run.passed_cases += 1
            await db.commit()
            if case_cancelled:
                break

        run = await _load_run(db, eval_run_id)
        cancelled = run.status == "cancelled"
        if cancelled:
            remaining = (
                (
                    await db.execute(
                        select(EvalCaseResult).where(
                            EvalCaseResult.eval_run_id == eval_run_id,
                            EvalCaseResult.status.in_(["pending", "running"]),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for item in remaining:
                item.status = "cancelled"
        else:
            run.status = "completed"
        run.current_case_key = None
        run.current_agent_run_id = None
        run.current_case_result_id = None
        final_results = (
            (
                await db.execute(
                    select(EvalCaseResult).where(EvalCaseResult.eval_run_id == eval_run_id)
                )
            )
            .scalars()
            .all()
        )
        run.metrics = aggregate_metrics(list(final_results))
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - surface fatal errors on the run
        await db.rollback()
        run = await _load_run(db, eval_run_id)
        if run:
            run.status = "failed"
            run.error_message = str(exc)
            await db.commit()
        raise
