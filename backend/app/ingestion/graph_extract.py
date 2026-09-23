from __future__ import annotations

import json
import re
from typing import Any

from app.prompts.graph import GRAPH_EXTRACTION_SYSTEM_PROMPT, SECTION_GRAPH_SYSTEM_PROMPT
from app.providers.deepseek import DeepSeekProvider

VALID_KINDS = {"Entity", "Method", "Dataset", "Metric", "Paper", "Experiment", "Result"}
VALID_RELATIONS = {
    "HAS_EXPERIMENT",
    "USES_METHOD",
    "USES_DATASET",
    "REPORTS_RESULT",
    "MEASURES",
    "CITES",
    "COMPARES_WITH",
    "RELATED_TO",
}


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "-")


def _normalize_entities(raw: Any) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    keys: set[str] = set()
    if not isinstance(raw, list):
        return entities
    for item in raw:
        if isinstance(item, str):
            item = {"key": item, "name": item, "kind": "Entity"}
        if not isinstance(item, dict):
            continue
        key = _normalize_key(item.get("key") or item.get("name"))
        name = str(item.get("name") or item.get("key") or "").strip()
        if not key or not name or key in keys:
            continue
        keys.add(key)
        kind = str(item.get("kind") or "Entity")
        entities.append(
            {"key": key, "name": name, "kind": kind if kind in VALID_KINDS else "Entity"}
        )
    return entities


def _normalize_relations(raw: Any, keys: set[str], model_name: str) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return relations
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = _normalize_key(item.get("source"))
        target = _normalize_key(item.get("target"))
        if source not in keys or target not in keys:
            continue
        kind = str(item.get("kind") or "RELATED_TO").upper()
        try:
            confidence = min(max(float(item.get("confidence") or 0.5), 0.0), 1.0)
        except (TypeError, ValueError):
            confidence = 0.5
        relations.append(
            {
                "source": source,
                "target": target,
                "kind": kind if kind in VALID_RELATIONS else "RELATED_TO",
                "confidence": confidence,
                "extractor_model": model_name,
                "extractor_version": "1",
            }
        )
    return relations


def _parse_json(raw: str) -> Any:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _parse_payload(data: Any, model_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        return [], []
    entities = _normalize_entities(data.get("entities"))
    keys = {item["key"] for item in entities}
    relations = _normalize_relations(data.get("relations"), keys, model_name)
    return entities, relations


async def extract_graph(
    text: str,
    provider: DeepSeekProvider | None,
    model_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """LLM-only extraction. A missing provider or malformed output yields an empty graph."""
    if provider is None or not text.strip():
        return [], []
    try:
        response = await provider.invoke(
            [
                {"role": "system", "content": GRAPH_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            [],
        )
        return _parse_payload(_parse_json(response.content), model_name)
    except Exception:
        return [], []


async def extract_graph_batch(
    texts: list[str],
    provider: DeepSeekProvider | None,
    model_name: str,
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Extract entities/relations for several chunks in one model call."""
    if provider is None or len(texts) <= 1:
        return [await extract_graph(text, provider, model_name) for text in texts]
    segments = [f"[片段 {index}]\n{text}" for index, text in enumerate(texts)]
    payload = "\n\n".join(segments)
    instruction = (
        "下面有多个论文片段。请只返回一个 JSON 数组，数组每个元素形如 "
        '{"index": 片段编号, "entities": [...], "relations": [...]}。'
        "entities 必须是对象数组（含 key/name/kind），禁止字符串数组；"
        "relations 中 source/target 必须引用该片段 entities 的 key。"
    )
    try:
        response = await provider.invoke(
            [
                {"role": "system", "content": GRAPH_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"{instruction}\n\n{payload}"},
            ],
            [],
        )
        data = _parse_json(response.content)
        if not isinstance(data, list):
            return [([], []) for _ in texts]
        grouped: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(texts):
                grouped[index] = _parse_payload(item, model_name)
        return [grouped.get(index, ([], [])) for index in range(len(texts))]
    except Exception:
        return [([], []) for _ in texts]


def _flatten_experiments(
    items: Any, model_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    keys: set[str] = set()

    def add(value: Any, kind: str, fallback: str = "") -> str | None:
        if isinstance(value, dict):
            key = _normalize_key(value.get("key") or value.get("name"))
            name = str(value.get("name") or value.get("key") or "").strip() or fallback
        else:
            key = _normalize_key(value)
            name = str(value or "").strip() or fallback
        if not key or not name:
            return None
        if key not in keys:
            keys.add(key)
            entities.append({"key": key, "name": name, "kind": kind})
        return key

    def relate(source: str, target: str, kind: str) -> None:
        relations.append(
            {
                "source": source,
                "target": target,
                "kind": kind,
                "confidence": 0.7,
                "extractor_model": model_name,
                "extractor_version": "1",
            }
        )

    if not isinstance(items, list):
        return entities, relations
    for experiment in items:
        if not isinstance(experiment, dict):
            continue
        experiment_key = add(
            experiment.get("key") or experiment.get("name"), "Experiment", "experiment"
        )
        if experiment_key is None:
            continue
        for method in experiment.get("methods") or []:
            method_key = add(method, "Method")
            if method_key:
                relate(experiment_key, method_key, "USES_METHOD")
        for dataset in experiment.get("datasets") or []:
            dataset_key = add(dataset, "Dataset")
            if dataset_key:
                relate(experiment_key, dataset_key, "USES_DATASET")
        for result in experiment.get("results") or []:
            if not isinstance(result, dict):
                result = {"name": result}
            result_key = add(result.get("key") or result.get("name"), "Result", "result")
            if result_key is None:
                continue
            relate(experiment_key, result_key, "REPORTS_RESULT")
            metric = result.get("metric")
            if metric:
                metric_key = add(metric, "Metric")
                if metric_key:
                    relate(result_key, metric_key, "MEASURES")
    return entities, relations


async def extract_section_graph(
    section_title: str,
    segments: list[str],
    provider: DeepSeekProvider | None,
    model_name: str,
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Extract one section at a time so one experiment is not split into duplicates."""
    if not segments:
        return []
    if provider is None:
        return [([], []) for _ in segments]
    payload = "\n\n".join(f"[片段 {index}]\n{text}" for index, text in enumerate(segments))
    prompt = f"章节标题：{section_title}\n\n{payload}"
    try:
        response = await provider.invoke(
            [
                {"role": "system", "content": SECTION_GRAPH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            [],
        )
        data = _parse_json(response.content)
    except Exception:
        return [([], []) for _ in segments]
    grouped: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(segments):
                grouped[index] = _flatten_experiments(item.get("experiments"), model_name)
    return [grouped.get(index, ([], [])) for index in range(len(segments))]
