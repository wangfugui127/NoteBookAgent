from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document, DocumentVersion, Section
from app.providers.siliconflow import SiliconFlowProvider
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.milvus import MilvusStore
from app.retrieval.neo4j_store import Neo4jStore
from app.retrieval.types import SearchHit

RetrievalMode = Literal["hybrid", "hybrid_graph", "layered", "auto", "comprehensive"]


def should_expand_graph(query: str) -> bool:
    signals = ("关系", "比较", "引用", "方法", "数据集", "指标", "支持", "反驳", "关联")
    return (
        any(signal in query for signal in signals)
        or len(re.findall(r"[A-Z][A-Za-z0-9-]{2,}", query)) >= 2
    )


def entity_candidates(query: str) -> list[str]:
    english = re.findall(r"\b[A-Z][A-Za-z0-9-]{2,}\b", query)
    quoted = re.findall(r"[“\"]([^”\"]{2,40})[”\"]", query)
    return list(dict.fromkeys([*english, *quoted]))[:12]


class RetrievalService:
    def __init__(
        self,
        milvus: MilvusStore,
        neo4j: Neo4jStore,
        siliconflow: SiliconFlowProvider,
    ) -> None:
        self.milvus = milvus
        self.neo4j = neo4j
        self.siliconflow = siliconflow

    async def _graph_hits(
        self, db: AsyncSession, notebook_id: str, candidates: list[str], limit: int
    ) -> tuple[list[SearchHit], bool]:
        if not await self.neo4j.verify():
            return [], True
        chunk_ids = await self.neo4j.expand(notebook_id, candidates, limit)
        if not chunk_ids:
            return [], False
        rows = (
            await db.execute(
                select(Chunk, DocumentVersion, Document, Section)
                .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
                .join(Document, DocumentVersion.document_id == Document.id)
                .join(Section, Chunk.section_id == Section.id, isouter=True)
                .where(Chunk.id.in_(chunk_ids), Chunk.is_active.is_(True))
            )
        ).all()
        ordered = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        hits = [
            SearchHit(
                chunk_id=chunk.id,
                text=chunk.content,
                score=1.0 / (ordered.get(chunk.id, limit) + 1),
                document_id=document.id,
                document_version_id=version.id,
                title=document.title,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section_id=chunk.section_id,
                section_title=section.title if section else None,
                ordinal=chunk.ordinal,
                sources=["neo4j"],
            )
            for chunk, version, document, section in rows
        ]
        hits.sort(key=lambda hit: ordered.get(hit.chunk_id, limit))
        return hits, False

    async def _attach_sections(
        self, db: AsyncSession, hits: list[SearchHit]
    ) -> None:
        missing = {hit.section_id for hit in hits if hit.section_id and not hit.section_title}
        if not missing:
            return
        rows = (
            await db.execute(select(Section.id, Section.title).where(Section.id.in_(missing)))
        ).all()
        titles = {row[0]: row[1] for row in rows}
        for hit in hits:
            if hit.section_id and not hit.section_title:
                hit.section_title = titles.get(hit.section_id)

    async def _document_candidates(
        self,
        query: str,
        vector: list[float],
        notebook_id: str,
        document_ids: list[str] | None,
        limit: int,
    ) -> list[str]:
        hits = await asyncio.to_thread(
            self.milvus.search_documents,
            query,
            vector,
            notebook_id,
            document_ids,
            limit,
        )
        candidate_ids = list(
            dict.fromkeys(str(hit["entity"]["document_id"]) for hit in hits)
        )
        if document_ids:
            allowed = set(document_ids)
            candidate_ids = [item for item in candidate_ids if item in allowed]
        return candidate_ids

    async def search(
        self,
        db: AsyncSession,
        *,
        notebook_id: str,
        query: str,
        document_ids: list[str] | None,
        mode: RetrievalMode = "auto",
        top_k: int = 8,
    ) -> dict[str, object]:
        vector = (await self.siliconflow.embed([query]))[0]
        layered_requested = mode in {"layered", "auto", "comprehensive"}
        layered_used = False
        layered_degraded = False
        candidate_documents = document_ids
        if layered_requested:
            try:
                docs = await self._document_candidates(
                    query, vector, notebook_id, document_ids, 10
                )
            except Exception:
                docs = []
            if docs:
                layered_used = True
                candidate_documents = docs
            elif mode == "layered":
                layered_degraded = True

        hybrid = await asyncio.to_thread(
            self.milvus.hybrid_search,
            query,
            vector,
            notebook_id,
            candidate_documents,
            None,
            30,
        )
        use_graph = mode in {"hybrid_graph", "comprehensive"} or (
            mode == "auto" and should_expand_graph(query)
        )
        candidates = entity_candidates(query) if use_graph else []
        graph_attempted = bool(use_graph and candidates)
        graph_hits: list[SearchHit] = []
        graph_degraded = False
        if graph_attempted:
            graph_hits, graph_degraded = await self._graph_hits(db, notebook_id, candidates, 30)
        fused = reciprocal_rank_fusion(
            [("hybrid", hybrid), *(([("neo4j", graph_hits)]) if graph_hits else [])], limit=30
        )
        reranked = await self.siliconflow.rerank(query, [item.text for item in fused], top_k)
        final: list[SearchHit] = []
        for entry in reranked:
            index = int(entry["index"])
            if index >= len(fused):
                continue
            hit = fused[index]
            hit.score = float(entry.get("relevance_score") or hit.score)
            final.append(hit)
        await self._attach_sections(db, final)
        return {
            "mode_requested": mode,
            "mode_used": "layered" if layered_used else "hybrid",
            "layered_used": layered_used,
            "layered_degraded": layered_degraded,
            "graph_attempted": graph_attempted,
            "graph_used": bool(graph_hits),
            "graph_degraded": graph_degraded,
            "items": [asdict(item) for item in final],
        }

    async def close(self) -> None:
        await self.siliconflow.close()
        await self.neo4j.close()
        close = getattr(self.milvus.client, "close", None)
        if callable(close):
            close()
