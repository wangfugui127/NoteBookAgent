from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.evaluation.service import (
    create_run_snapshot,
    dataset_has_metrics,
    missing_sources_for,
)
from app.models import EvalCaseResult, EvalRun


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


def _case(key: str, **overrides: object) -> SimpleNamespace:
    base = {
        "case_key": key,
        "question": f"question-{key}",
        "expected_tools": [],
        "expected_source_titles": [],
        "required_keywords": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_dataset_has_metrics_detects_configured_dimensions() -> None:
    assert not dataset_has_metrics([_case("a"), _case("b")])
    assert dataset_has_metrics([_case("a"), _case("b", expected_tools=["search_notebook"])])
    assert dataset_has_metrics([_case("a", required_keywords=["数据集"])])


def test_missing_sources_reports_only_configured_and_absent() -> None:
    cases = [
        _case("a", expected_source_titles=["水稻", "小麦"]),
        _case("b", expected_source_titles=["玉米"]),
        _case("c", expected_tools=["search_notebook"]),
    ]
    report = missing_sources_for(cases, ["水稻遥感.pdf"])
    assert report == [
        {"case_key": "a", "question": "question-a", "missing": ["小麦"]},
        {"case_key": "b", "question": "question-b", "missing": ["玉米"]},
    ]


@pytest.mark.asyncio
async def test_create_run_snapshot_copies_cases_as_pending() -> None:
    db = FakeDb()
    user = SimpleNamespace(id="user-1")
    dataset = SimpleNamespace(id="dataset-1", name="基础评测")
    cases = [
        _case("a", expected_tools=["search_notebook"], expected_source_titles=["水稻"]),
        _case("b", required_keywords=["数据集"]),
    ]
    run = await create_run_snapshot(
        db,
        user=user,
        notebook_id="nb-1",
        dataset=dataset,
        cases=cases,
        missing_map={"a": ["水稻"]},
        score_config={"route_weight": 0.5, "pass_threshold": 70},
    )

    results = [item for item in db.added if isinstance(item, EvalCaseResult)]
    assert isinstance(run, EvalRun)
    assert run.total_cases == 2
    assert run.dataset_name == "基础评测"
    assert run.score_config["pass_threshold"] == 70
    assert len(results) == 2
    assert results[0].status == "pending"
    assert results[0].eval_run_id == run.id
    assert results[0].missing_sources == ["水稻"]
    assert results[0].expected_tools == ["search_notebook"]
    assert results[1].ordinal == 2
