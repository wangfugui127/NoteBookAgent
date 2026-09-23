from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_SCORE_CONFIG: dict[str, float] = {
    "route_weight": 0.30,
    "retrieval_weight": 0.30,
    "citation_weight": 0.20,
    "keyword_weight": 0.20,
    "pass_threshold": 60.0,
}

METRIC_FIELDS = ("expected_tools", "expected_source_titles", "required_keywords")


def normalize_terms(values: list[str] | None) -> list[str]:
    return [str(item).strip() for item in (values or []) if str(item).strip()]


def match_titles(expected: list[str], titles: list[str]) -> tuple[list[str], list[str]]:
    """Match expected source titles against observed document titles (substring)."""
    lowered = [str(title).strip().lower() for title in titles if str(title).strip()]
    matched: list[str] = []
    missing: list[str] = []
    for item in normalize_terms(expected):
        needle = item.lower()
        if any(needle in title or title in needle for title in lowered):
            matched.append(item)
        else:
            missing.append(item)
    return matched, missing


def score_route(expected: list[str], actual: list[str]) -> float:
    expected_terms = set(normalize_terms(expected))
    if not expected_terms:
        return 1.0
    actual_terms = set(normalize_terms(actual))
    return len(expected_terms & actual_terms) / len(expected_terms)


def score_keywords(required: list[str], answer: str | None) -> tuple[float, list[str], list[str]]:
    required_terms = normalize_terms(required)
    if not required_terms:
        return 1.0, [], []
    text = (answer or "").lower()
    matched = [term for term in required_terms if term.lower() in text]
    missing = [term for term in required_terms if term not in matched]
    return len(matched) / len(required_terms), matched, missing


@dataclass
class CaseScore:
    route_score: float | None
    retrieval_score: float | None
    citation_score: float | None
    keyword_score: float | None
    total_score: float | None
    passed: bool
    status: str
    matched_sources: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def score_case(
    *,
    expected_tools: list[str],
    actual_tools: list[str],
    expected_source_titles: list[str],
    evidence_titles: list[str],
    citation_titles: list[str],
    missing_sources: list[str],
    required_keywords: list[str],
    answer: str | None,
    run_status: str,
    score_config: dict[str, float] | None = None,
) -> CaseScore:
    config = {**DEFAULT_SCORE_CONFIG, **(score_config or {})}
    expected_tools = normalize_terms(expected_tools)
    expected_sources = normalize_terms(expected_source_titles)
    required_keywords = normalize_terms(required_keywords)
    missing_sources = normalize_terms(missing_sources)

    route: float | None = None
    retrieval: float | None = None
    citation: float | None = None
    keyword: float | None = None
    matched_sources: list[str] = []
    matched_citations: list[str] = []
    matched_keywords: list[str] = []
    missing_keywords: list[str] = []

    if expected_tools:
        route = score_route(expected_tools, actual_tools)
    if expected_sources:
        matched_sources, _ = match_titles(expected_sources, evidence_titles)
        matched_citations, _ = match_titles(expected_sources, citation_titles)
        retrieval = len(matched_sources) / len(expected_sources)
        citation = len(matched_citations) / len(expected_sources)
        if missing_sources:
            # Expected documents absent from the notebook: no retrieval/citation credit.
            retrieval = 0.0
            citation = 0.0
    if required_keywords:
        keyword, matched_keywords, missing_keywords = score_keywords(required_keywords, answer)

    active: list[tuple[float, float]] = []
    if expected_tools and route is not None:
        active.append((route, float(config["route_weight"])))
    if expected_sources and retrieval is not None and citation is not None:
        active.append((retrieval, float(config["retrieval_weight"])))
        active.append((citation, float(config["citation_weight"])))
    if required_keywords and keyword is not None:
        active.append((keyword, float(config["keyword_weight"])))

    detail: dict[str, Any] = {
        "matched_sources": matched_sources,
        "matched_citations": matched_citations,
        "matched_keywords": matched_keywords,
        "missing_keywords": missing_keywords,
        "missing_sources": missing_sources,
        "run_status": run_status,
    }

    if not active:
        detail["score_note"] = "未配置任何评分维度，无法打分"
        return CaseScore(
            route_score=None,
            retrieval_score=None,
            citation_score=None,
            keyword_score=None,
            total_score=None,
            passed=False,
            status="error",
            matched_sources=matched_sources,
            missing_keywords=missing_keywords,
            detail=detail,
        )

    total = sum(score * weight for score, weight in active) / sum(
        weight for _, weight in active
    )
    total *= 100
    completed = run_status == "completed"
    passed = completed and total >= float(config["pass_threshold"])
    status = "error" if not completed else ("passed" if passed else "failed")
    return CaseScore(
        route_score=route,
        retrieval_score=retrieval,
        citation_score=citation,
        keyword_score=keyword,
        total_score=round(total, 1),
        passed=passed,
        status=status,
        matched_sources=matched_sources,
        missing_keywords=missing_keywords,
        detail=detail,
    )


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def aggregate_metrics(results: list[Any]) -> dict[str, Any]:
    """Aggregate EvalCaseResult-like objects into run-level metrics."""
    total = len(results)
    passed = sum(1 for item in results if getattr(item, "passed", False))
    route = [
        item.route_score
        for item in results
        if item.route_score is not None and item.expected_tools
    ]
    retrieval = [
        item.retrieval_score
        for item in results
        if item.retrieval_score is not None and item.expected_source_titles
    ]
    citation = [
        item.citation_score
        for item in results
        if item.citation_score is not None and item.expected_source_titles
    ]
    keyword = [
        item.keyword_score
        for item in results
        if item.keyword_score is not None and item.required_keywords
    ]
    latency = [item.latency_ms for item in results if getattr(item, "latency_ms", None) is not None]
    totals = [item.total_score for item in results if item.total_score is not None]
    return {
        "total_cases": total,
        "completed_cases": sum(1 for item in results if item.status in {"passed", "failed"}),
        "passed_cases": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "route_accuracy": _mean(route),
        "retrieval_accuracy": _mean(retrieval),
        "citation_accuracy": _mean(citation),
        "keyword_coverage": _mean(keyword),
        "avg_total_score": _mean(totals),
        "avg_latency_ms": (
            round(sum(latency) / len(latency)) if latency else None
        ),
    }
