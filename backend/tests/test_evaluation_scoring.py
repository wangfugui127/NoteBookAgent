from __future__ import annotations

from types import SimpleNamespace

from app.evaluation.scorers import (
    DEFAULT_SCORE_CONFIG,
    aggregate_metrics,
    match_titles,
    score_case,
    score_keywords,
    score_route,
)


def test_route_score_matches_expected_tools() -> None:
    assert score_route(["search_notebook"], ["search_notebook"]) == 1.0
    assert score_route(["search_notebook", "get_notebook_items"], ["search_notebook"]) == 0.5
    assert score_route([], ["anything"]) == 1.0


def test_match_titles_uses_substring_and_reports_missing() -> None:
    matched, missing = match_titles(["水稻", "小麦"], ["水稻遥感论文.pdf", "其他.pdf"])
    assert matched == ["水稻"]
    assert missing == ["小麦"]


def test_keyword_score_handles_empty_requirement() -> None:
    score, matched, missing = score_keywords([], "任意回答")
    assert (score, matched, missing) == (1.0, [], [])
    score, matched, missing = score_keywords(["数据集", "模型"], "本文给出数据集说明。")
    assert score == 0.5
    assert matched == ["数据集"]
    assert missing == ["模型"]


def test_score_case_renormalizes_only_configured_metrics() -> None:
    # Only route + keyword configured: total is renormalized over 0.3 + 0.2.
    result = score_case(
        expected_tools=["search_notebook"],
        actual_tools=["search_notebook"],
        expected_source_titles=[],
        evidence_titles=[],
        citation_titles=[],
        missing_sources=[],
        required_keywords=["数据集"],
        answer="本文使用了公开数据集。",
        run_status="completed",
    )
    assert result.route_score == 1.0
    assert result.keyword_score == 1.0
    assert result.retrieval_score is None
    assert result.citation_score is None
    assert result.total_score == 100.0
    assert result.passed is True


def test_score_case_empty_config_is_error_not_free_pass() -> None:
    result = score_case(
        expected_tools=[],
        actual_tools=[],
        expected_source_titles=[],
        evidence_titles=[],
        citation_titles=[],
        missing_sources=[],
        required_keywords=[],
        answer="任意回答",
        run_status="completed",
    )
    assert result.total_score is None
    assert result.passed is False
    assert result.status == "error"


def test_score_case_missing_sources_zeroes_retrieval_and_citation() -> None:
    result = score_case(
        expected_tools=[],
        actual_tools=[],
        expected_source_titles=["论文A", "论文B"],
        evidence_titles=["论文A.pdf", "论文B.pdf"],
        citation_titles=["论文A.pdf", "论文B.pdf"],
        missing_sources=["论文B"],
        required_keywords=[],
        answer="回答",
        run_status="completed",
    )
    assert result.retrieval_score == 0.0
    assert result.citation_score == 0.0


def test_score_case_separates_retrieval_and_citation() -> None:
    # Retrieved both documents but only cited one.
    result = score_case(
        expected_tools=[],
        actual_tools=[],
        expected_source_titles=["论文A", "论文B"],
        evidence_titles=["论文A.pdf", "论文B.pdf"],
        citation_titles=["论文A.pdf"],
        missing_sources=[],
        required_keywords=[],
        answer="回答",
        run_status="completed",
    )
    assert result.retrieval_score == 1.0
    assert result.citation_score == 0.5


def test_score_case_failed_run_is_error() -> None:
    result = score_case(
        expected_tools=["search_notebook"],
        actual_tools=["search_notebook"],
        expected_source_titles=[],
        evidence_titles=[],
        citation_titles=[],
        missing_sources=[],
        required_keywords=[],
        answer="",
        run_status="failed",
    )
    assert result.status == "error"
    assert result.passed is False


def test_aggregate_metrics_means() -> None:
    results = [
        SimpleNamespace(
            passed=True,
            status="passed",
            route_score=1.0,
            retrieval_score=1.0,
            citation_score=0.5,
            keyword_score=1.0,
            total_score=90.0,
            latency_ms=1000,
            expected_tools=["a"],
            expected_source_titles=["x"],
            required_keywords=["k"],
        ),
        SimpleNamespace(
            passed=False,
            status="failed",
            route_score=0.0,
            retrieval_score=0.0,
            citation_score=0.0,
            keyword_score=0.0,
            total_score=20.0,
            latency_ms=3000,
            expected_tools=["a"],
            expected_source_titles=["x"],
            required_keywords=["k"],
        ),
    ]
    metrics = aggregate_metrics(results)
    assert metrics["total_cases"] == 2
    assert metrics["passed_cases"] == 1
    assert metrics["pass_rate"] == 0.5
    assert metrics["route_accuracy"] == 0.5
    assert metrics["avg_latency_ms"] == 2000


def test_default_weights_sum_to_one() -> None:
    weights = sum(
        DEFAULT_SCORE_CONFIG[key]
        for key in ("route_weight", "retrieval_weight", "citation_weight", "keyword_weight")
    )
    assert abs(weights - 1.0) < 1e-9
