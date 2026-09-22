from __future__ import annotations

import json
import re
from typing import Any

from app.prompts.graph import GRAPH_EXTRACTION_SYSTEM_PROMPT
from app.providers.deepseek import DeepSeekProvider

ENTITY_PATTERN = re.compile(r"\b[A-Z][A-Za-z0-9_-]{2,}(?:\s+[A-Z][A-Za-z0-9_-]{2,}){0,3}\b")

VALID_KINDS = {"Entity", "Method", "Dataset", "Metric", "Paper"}
VALID_RELATIONS = {
    "USES_METHOD",
    "USES_DATASET",
    "MEASURES_METRIC",
    "CITES",
    "COMPARES_WITH",
    "SUPPORTS",
    "CONTRADICTS",
    "RELATED_TO",
}


def _kind(name: str) -> str:
    lower = name.lower()
    if any(value in lower for value in ("dataset", "corpus", "benchmark")):
        return "Dataset"
    if any(value in lower for value in ("accuracy", "precision", "recall", "f1", "rouge")):
        return "Metric"
    if any(value in lower for value in ("model", "network", "transformer", "method")):
        return "Method"
    if any(value in lower for value in ("paper", "study", "survey")):
        return "Paper"
    return "Entity"


def extract_graph_fallback(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Conservative no-key fallback; every edge still points to its evidence chunk."""
    names = list(dict.fromkeys(match.group(0).strip() for match in ENTITY_PATTERN.finditer(text)))[
        :20
    ]
    entities = [
        {"key": name.lower().replace(" ", "-"), "name": name, "kind": _kind(name)} for name in names
    ]
    relations = [
        {
            "source": entities[index]["key"],
            "target": entities[index + 1]["key"],
            "kind": "RELATED_TO",
            "confidence": 0.3,
            "extractor_model": "heuristic",
            "extractor_version": "1",
        }
        for index in range(len(entities) - 1)
    ]
    return entities, relations


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
        key = str(item.get("key") or item.get("name") or "").strip().lower().replace(" ", "-")
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
        source = str(item.get("source") or "").strip().lower().replace(" ", "-")
        target = str(item.get("target") or "").strip().lower().replace(" ", "-")
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
    if provider is None:
        return extract_graph_fallback(text)
    try:
        response = await provider.invoke(
            [
                {"role": "system", "content": GRAPH_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            [],
        )
        entities, relations = _parse_payload(_parse_json(response.content), model_name)
    except Exception:
        return extract_graph_fallback(text)
    if not entities:
        return extract_graph_fallback(text)
    return entities, relations


async def extract_graph_batch(
    texts: list[str],
    provider: DeepSeekProvider | None,
    model_name: str,
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Extract entities/relations for several chunks in one model call.

    Falls back to per-chunk extraction if the batched response is malformed.
    """
    if provider is None or len(texts) == 1:
        return [await extract_graph(text, provider, model_name) for text in texts]
    segments = [
        f"[片段 {index}]\n{text}" for index, text in enumerate(texts)
    ]
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
            raise ValueError("batch response is not a list")
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
        results: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
        for index, text in enumerate(texts):
            entities, relations = grouped.get(index, ([], []))
            if not entities:
                entities, relations = extract_graph_fallback(text)
            results.append((entities, relations))
        return results
    except Exception:
        return [await extract_graph(text, provider, model_name) for text in texts]
