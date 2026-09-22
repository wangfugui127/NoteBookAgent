from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Protocol

from app.agent.types import ToolSummary


class RouterProvider(Protocol):
    async def select_tools(
        self, query: str, catalog: list[ToolSummary], limit: int
    ) -> list[str]: ...


CORE_TOOL_HINTS: dict[str, tuple[str, ...]] = {
    "task_update": ("计划", "步骤", "进度", "task"),
    "list_notebook_sources": ("有哪些", "资料", "source", "文档列表"),
    "search_notebook": ("论文", "文档", "根据资料", "检索", "对比", "证据"),
    "get_notebook_items": ("原文", "详细", "上下文", "全文"),
    "search_papers": ("最新论文", "相关论文", "openalex", "外部"),
    "get_paper_details": ("论文详情", "作者", "doi", "摘要"),
    "load_skill": ("skill", "文献综述", "流程"),
    "tool_search": ("工具", "能力", "mcp"),
    "read_mcp_resource": ("mcp resource", "mcp资源"),
}


def _tokens(text: str) -> Counter[str]:
    words = re.findall(r"[\w\u3400-\u9fff]+", text.lower())
    grams: list[str] = []
    for word in words:
        grams.append(word)
        if any("\u3400" <= char <= "\u9fff" for char in word):
            grams.extend(word[index : index + 2] for index in range(max(0, len(word) - 1)))
    return Counter(grams)


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    dot = sum(value * right.get(key, 0) for key, value in left.items())
    norm_left = math.sqrt(sum(value * value for value in left.values()))
    norm_right = math.sqrt(sum(value * value for value in right.values()))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


class DefaultRouterProvider:
    """Deterministic first-version selector. JEV can replace this protocol later."""

    async def select_tools(
        self, query: str, catalog: list[ToolSummary], limit: int = 12
    ) -> list[str]:
        query_vector = _tokens(query)
        lower = query.lower()
        scored: list[tuple[float, str]] = []
        for item in catalog:
            score = _cosine(query_vector, _tokens(f"{item.name} {item.description}"))
            score += sum(0.35 for hint in CORE_TOOL_HINTS.get(item.name, ()) if hint in lower)
            if item.name in {"task_update", "search_notebook", "tool_search"}:
                score += 0.05
            scored.append((score, item.name))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        chosen = [name for score, name in scored if score > 0][: max(1, limit)]
        if not chosen and catalog:
            chosen = [catalog[0].name]
        return chosen


class EmbeddingRouterProvider:
    """Embedding selector with the deterministic router as an offline fallback."""

    def __init__(self, embedder: Any) -> None:
        self.embedder = embedder
        self.fallback = DefaultRouterProvider()
        self._cache_key: tuple[tuple[str, str], ...] = ()
        self._catalog_vectors: list[list[float]] = []

    async def select_tools(
        self, query: str, catalog: list[ToolSummary], limit: int = 12
    ) -> list[str]:
        try:
            cache_key = tuple((item.name, item.description) for item in catalog)
            if cache_key != self._cache_key:
                self._catalog_vectors = await self.embedder.embed(
                    [f"{item.name}: {item.description}" for item in catalog]
                )
                self._cache_key = cache_key
            query_vector = (await self.embedder.embed([query]))[0]

            def similarity(vector: list[float]) -> float:
                dot = sum(left * right for left, right in zip(query_vector, vector, strict=False))
                left_norm = math.sqrt(sum(value * value for value in query_vector))
                right_norm = math.sqrt(sum(value * value for value in vector))
                return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

            ranked = sorted(
                zip(catalog, self._catalog_vectors, strict=True),
                key=lambda pair: (-similarity(pair[1]), pair[0].name),
            )
            chosen = [item.name for item, _ in ranked[: max(1, limit)]]
            for core in ("task_update", "search_notebook", "tool_search"):
                if core in {item.name for item in catalog} and core not in chosen:
                    chosen.append(core)
            return chosen[:limit]
        except Exception:
            return await self.fallback.select_tools(query, catalog, limit)
