from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, func, select

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.evaluation.scorers import DEFAULT_SCORE_CONFIG
from app.evaluation.service import (
    create_run_snapshot,
    dataset_has_metrics,
    missing_sources_for,
    notebook_source_titles,
)
from app.evaluation.tasks import execute_evaluation_task
from app.models import (
    AgentRun,
    EvalCase,
    EvalCaseResult,
    EvalDataset,
    EvalRun,
    Notebook,
    RunStatus,
)
from app.schemas import (
    EvalCaseInput,
    EvalCaseUpdate,
    EvalCaseView,
    EvalDatasetCreate,
    EvalDatasetUpdate,
    EvalDatasetView,
    EvalImportRequest,
    EvalRunCreate,
    EvalRunView,
)

router = APIRouter(prefix="/eval", tags=["eval"])

RUN_TERMINAL = {"completed", "failed", "cancelled"}


async def _owned_dataset(db: DbSession, dataset_id: str, user_id: str) -> EvalDataset:
    dataset = await db.scalar(
        select(EvalDataset).where(EvalDataset.id == dataset_id, EvalDataset.user_id == user_id)
    )
    if not dataset:
        raise HTTPException(404, "dataset not found")
    return dataset


async def _owned_case(db: DbSession, case_id: str, user_id: str) -> EvalCase:
    case = await db.scalar(
        select(EvalCase)
        .join(EvalDataset, EvalDataset.id == EvalCase.dataset_id)
        .where(EvalCase.id == case_id, EvalDataset.user_id == user_id)
    )
    if not case:
        raise HTTPException(404, "case not found")
    return case


async def _owned_run(db: DbSession, run_id: str, user_id: str) -> EvalRun:
    run = await db.scalar(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.user_id == user_id)
    )
    if not run:
        raise HTTPException(404, "eval run not found")
    return run


async def _unique_case_key(db: DbSession, dataset_id: str, base: str | None) -> str:
    stem = (base or "").strip() or f"case-{uuid.uuid4().hex[:8]}"
    existing = set(
        (
            await db.execute(
                select(EvalCase.case_key).where(EvalCase.dataset_id == dataset_id)
            )
        )
        .scalars()
        .all()
    )
    if stem not in existing:
        return stem
    index = 2
    while f"{stem}-{index}" in existing:
        index += 1
    return f"{stem}-{index}"


@router.get("/datasets")
async def list_datasets(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    datasets = (
        (
            await db.execute(
                select(EvalDataset)
                .where(EvalDataset.user_id == user.id)
                .order_by(EvalDataset.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    items: list[dict[str, Any]] = []
    for dataset in datasets:
        case_count = await db.scalar(
            select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset.id)
        )
        latest = await db.scalar(
            select(EvalRun)
            .where(EvalRun.dataset_id == dataset.id, EvalRun.user_id == user.id)
            .order_by(EvalRun.created_at.desc())
            .limit(1)
        )
        items.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "description": dataset.description,
                "created_at": dataset.created_at,
                "case_count": int(case_count or 0),
                "latest_run": (
                    {
                        "id": latest.id,
                        "status": latest.status,
                        "pass_rate": (latest.metrics or {}).get("pass_rate"),
                        "created_at": latest.created_at,
                    }
                    if latest
                    else None
                ),
            }
        )
    return {"items": items}


@router.post("/datasets", response_model=EvalDatasetView, status_code=201)
async def create_dataset(
    payload: EvalDatasetCreate, db: DbSession, user: CurrentUser
) -> EvalDataset:
    dataset = EvalDataset(user_id=user.id, name=payload.name, description=payload.description)
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.patch("/datasets/{dataset_id}", response_model=EvalDatasetView)
async def update_dataset(
    dataset_id: str, payload: EvalDatasetUpdate, db: DbSession, user: CurrentUser
) -> EvalDataset:
    dataset = await _owned_dataset(db, dataset_id, user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(dataset, key, value)
    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: str, db: DbSession, user: CurrentUser) -> None:
    dataset = await _owned_dataset(db, dataset_id, user.id)
    await db.execute(delete(EvalDataset).where(EvalDataset.id == dataset.id))
    await db.commit()


@router.get("/datasets/{dataset_id}")
async def dataset_detail(dataset_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    dataset = await _owned_dataset(db, dataset_id, user.id)
    cases = (
        (
            await db.execute(
                select(EvalCase)
                .where(EvalCase.dataset_id == dataset.id)
                .order_by(EvalCase.ordinal, EvalCase.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "created_at": dataset.created_at,
        "cases": [EvalCaseView.model_validate(case) for case in cases],
    }


@router.post("/datasets/{dataset_id}/cases", response_model=EvalCaseView, status_code=201)
async def create_case(
    dataset_id: str, payload: EvalCaseInput, db: DbSession, user: CurrentUser
) -> EvalCase:
    dataset = await _owned_dataset(db, dataset_id, user.id)
    next_ordinal = int(
        await db.scalar(
            select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset.id)
        )
        or 0
    ) + 1
    case = EvalCase(
        dataset_id=dataset.id,
        case_key=await _unique_case_key(db, dataset.id, payload.case_key),
        question=payload.question,
        expected_tools=payload.expected_tools,
        expected_source_titles=payload.expected_source_titles,
        required_keywords=payload.required_keywords,
        ordinal=next_ordinal,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


@router.patch("/cases/{case_id}", response_model=EvalCaseView)
async def update_case(
    case_id: str, payload: EvalCaseUpdate, db: DbSession, user: CurrentUser
) -> EvalCase:
    case = await _owned_case(db, case_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    if "case_key" in data and data["case_key"]:
        data["case_key"] = await _unique_case_key(db, case.dataset_id, data["case_key"])
    for key, value in data.items():
        if value is not None:
            setattr(case, key, value)
    await db.commit()
    await db.refresh(case)
    return case


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(case_id: str, db: DbSession, user: CurrentUser) -> None:
    case = await _owned_case(db, case_id, user.id)
    await db.execute(delete(EvalCase).where(EvalCase.id == case.id))
    await db.commit()


async def _insert_cases(
    db: DbSession, dataset: EvalDataset, cases: list[EvalCaseInput], replace: bool
) -> int:
    if replace:
        await db.execute(delete(EvalCase).where(EvalCase.dataset_id == dataset.id))
        await db.flush()
    existing = int(
        await db.scalar(
            select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset.id)
        )
        or 0
    )
    for offset, item in enumerate(cases, start=1):
        db.add(
            EvalCase(
                dataset_id=dataset.id,
                case_key=await _unique_case_key(db, dataset.id, item.case_key),
                question=item.question,
                expected_tools=item.expected_tools,
                expected_source_titles=item.expected_source_titles,
                required_keywords=item.required_keywords,
                ordinal=existing + offset,
            )
        )
        await db.flush()
    await db.commit()
    return existing + len(cases)


@router.post("/datasets/{dataset_id}/import")
async def import_cases(
    dataset_id: str, payload: EvalImportRequest, db: DbSession, user: CurrentUser
) -> dict[str, int]:
    dataset = await _owned_dataset(db, dataset_id, user.id)
    total = await _insert_cases(db, dataset, payload.cases, payload.replace)
    return {"case_count": total}


def _read_golden_sample(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(404, f"golden sample not found at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"invalid golden sample file: {exc}") from exc


@router.post("/datasets/import-default", response_model=EvalDatasetView, status_code=201)
async def import_default_dataset(db: DbSession, user: CurrentUser) -> EvalDataset:
    settings = get_settings()
    payload = await asyncio.to_thread(_read_golden_sample, Path(settings.eval_golden_path))
    dataset = EvalDataset(
        user_id=user.id,
        name=str(payload.get("name") or "示例评测集"),
        description=str(payload.get("description") or "示例题目，请按你的资料修改后再运行。"),
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    cases = [EvalCaseInput.model_validate(item) for item in payload.get("cases") or []]
    await _insert_cases(db, dataset, cases, replace=False)
    return dataset


@router.post("/datasets/{dataset_id}/runs", response_model=EvalRunView, status_code=202)
async def start_run(
    dataset_id: str, payload: EvalRunCreate, db: DbSession, user: CurrentUser
) -> EvalRun:
    dataset = await _owned_dataset(db, dataset_id, user.id)
    notebook = await db.scalar(
        select(Notebook).where(Notebook.id == payload.notebook_id, Notebook.owner_id == user.id)
    )
    if not notebook:
        raise HTTPException(404, "notebook not found")
    cases = (
        (
            await db.execute(
                select(EvalCase)
                .where(EvalCase.dataset_id == dataset.id)
                .order_by(EvalCase.ordinal, EvalCase.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not cases:
        raise HTTPException(422, "评测集还没有题目，请先添加题目")
    if not dataset_has_metrics(list(cases)):
        raise HTTPException(
            422,
            "评测集未配置任何评分维度：请为题目填写期望工具、期望来源或关键点",
        )
    titles = await notebook_source_titles(db, notebook.id)
    missing = missing_sources_for(list(cases), titles)
    if missing and not payload.allow_missing:
        raise HTTPException(
            409,
            {
                "message": "目标 Notebook 缺少部分预期文档，请补充文档或选择仍然开始。",
                "missing_sources": missing,
            },
        )
    missing_map = {item["case_key"]: item["missing"] for item in missing}
    run = await create_run_snapshot(
        db,
        user=user,
        notebook_id=notebook.id,
        dataset=dataset,
        cases=list(cases),
        missing_map=missing_map,
        score_config=DEFAULT_SCORE_CONFIG,
    )
    execute_evaluation_task.delay(run.id)
    return run


@router.get("/runs")
async def list_runs(
    db: DbSession, user: CurrentUser, notebook_id: str | None = None, limit: int = 20
) -> dict[str, Any]:
    statement = select(EvalRun).where(EvalRun.user_id == user.id)
    if notebook_id:
        statement = statement.where(EvalRun.notebook_id == notebook_id)
    bounded = max(1, min(limit, 100))
    runs = (
        (await db.execute(statement.order_by(EvalRun.created_at.desc()).limit(bounded)))
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": run.id,
                "dataset_name": run.dataset_name,
                "status": run.status,
                "total_cases": run.total_cases,
                "completed_cases": run.completed_cases,
                "passed_cases": run.passed_cases,
                "current_case_key": run.current_case_key,
                "metrics": run.metrics,
                "created_at": run.created_at,
            }
            for run in runs
        ]
    }


@router.get("/runs/{run_id}", response_model=EvalRunView)
async def get_run(run_id: str, db: DbSession, user: CurrentUser) -> EvalRun:
    return await _owned_run(db, run_id, user.id)


@router.get("/runs/{run_id}/results")
async def get_run_results(run_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    run = await _owned_run(db, run_id, user.id)
    results = (
        (
            await db.execute(
                select(EvalCaseResult)
                .where(EvalCaseResult.eval_run_id == run.id)
                .order_by(EvalCaseResult.ordinal)
            )
        )
        .scalars()
        .all()
    )
    return {
        "run": EvalRunView.model_validate(run),
        "items": [
            {
                "id": item.id,
                "case_key": item.case_key,
                "ordinal": item.ordinal,
                "question": item.question,
                "status": item.status,
                "expected_tools": item.expected_tools,
                "actual_tools": item.actual_tools,
                "expected_source_titles": item.expected_source_titles,
                "matched_sources": item.matched_sources,
                "missing_sources": item.missing_sources,
                "required_keywords": item.required_keywords,
                "matched_keywords": item.matched_keywords,
                "answer": item.answer,
                "route_score": item.route_score,
                "retrieval_score": item.retrieval_score,
                "citation_score": item.citation_score,
                "keyword_score": item.keyword_score,
                "total_score": item.total_score,
                "passed": item.passed,
                "latency_ms": item.latency_ms,
                "agent_run_id": item.agent_run_id,
                "error_message": item.error_message,
                "detail": item.detail,
            }
            for item in results
        ],
    }


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str, db: DbSession, user: CurrentUser) -> dict[str, str]:
    run = await _owned_run(db, run_id, user.id)
    if run.status in RUN_TERMINAL:
        raise HTTPException(409, "evaluation already finished")
    run.status = "cancelled"
    if run.current_agent_run_id:
        agent_run = await db.get(AgentRun, run.current_agent_run_id)
        if agent_run and agent_run.user_id == user.id:
            agent_run.status = RunStatus.cancelled
    await db.commit()
    return {"status": "cancelled"}
