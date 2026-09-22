from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import delete, select

from app.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import SessionFactory
from app.ingestion.chunker import SectionDraft, chunk_document, detect_sections
from app.ingestion.graph_extract import extract_graph_batch
from app.ingestion.parser import parse_document
from app.ingestion.profile import build_document_profile
from app.models import (
    Chunk,
    Document,
    DocumentProfile,
    DocumentVersion,
    IngestionJob,
    Section,
)
from app.providers.deepseek import DeepSeekProvider
from app.providers.siliconflow import SiliconFlowProvider
from app.retrieval.milvus import MilvusStore
from app.retrieval.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)
GRAPH_BATCH_SIZE = 4


async def ingest_document_version(document_version_id: str) -> None:
    """Parse, chunk, profile and index a document, then hand off graph building."""
    settings = get_settings()
    async with SessionFactory() as db:
        row = (
            await db.execute(
                select(DocumentVersion, Document, IngestionJob)
                .join(Document, DocumentVersion.document_id == Document.id)
                .join(IngestionJob, IngestionJob.document_version_id == DocumentVersion.id)
                .where(DocumentVersion.id == document_version_id)
            )
        ).one()
        version, document, job = row
        try:
            version.status = "parsing"
            job.status = "running"
            job.progress = 5
            await db.commit()
            parsed = parse_document(Path(version.storage_path), document.media_type)
            drafts = chunk_document(parsed)
            section_drafts = detect_sections(parsed)
            version.full_text = parsed.text
            await db.execute(delete(Chunk).where(Chunk.document_version_id == version.id))
            await db.execute(delete(Section).where(Section.document_version_id == version.id))
            sections: list[tuple[SectionDraft, Section]] = []
            for draft in section_drafts:
                section = Section(
                    document_version_id=version.id,
                    title=draft.title,
                    ordinal=draft.ordinal,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                )
                db.add(section)
                sections.append((draft, section))
            await db.flush()
            chunks: list[Chunk] = []
            for draft in drafts:
                midpoint = (draft.char_start + draft.char_end) // 2
                section = next(
                    (
                        item
                        for section_draft, item in sections
                        if section_draft.char_start <= midpoint < section_draft.char_end
                    ),
                    sections[-1][1],
                )
                chunk = Chunk(
                    document_version_id=version.id,
                    section_id=section.id,
                    ordinal=draft.ordinal,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    char_start=draft.char_start,
                    char_end=draft.char_end,
                    content=draft.content,
                    content_hash=draft.content_hash,
                )
                db.add(chunk)
                chunks.append(chunk)
            await db.flush()
            job.progress = 20
            await db.commit()

            llm = DeepSeekProvider(settings) if settings.deepseek_api_key else None
            try:
                profile = await build_document_profile(
                    title=document.title,
                    full_text=parsed.text,
                    section_titles=[draft.title for draft, _ in sections],
                    provider=llm,
                    model_name=settings.deepseek_model,
                )
                await db.execute(
                    delete(DocumentProfile).where(
                        DocumentProfile.document_version_id == version.id
                    )
                )
                db.add(
                    DocumentProfile(
                        document_version_id=version.id,
                        document_id=document.id,
                        notebook_id=document.notebook_id,
                        authors=list(profile.get("authors") or []),
                        year=profile.get("year"),
                        keywords=list(profile.get("keywords") or []),
                        abstract=str(profile.get("abstract") or ""),
                        abstract_source=str(profile.get("abstract_source") or "missing"),
                        region=profile.get("region") or None,
                        time_range=profile.get("time_range") or None,
                        metadata_json={},
                        one_sentence=str(profile.get("one_sentence") or ""),
                        data_and_method=str(profile.get("data_and_method") or ""),
                        results_conclusion=str(profile.get("results_conclusion") or ""),
                        contribution_limitations=str(
                            profile.get("contribution_limitations") or ""
                        ),
                        profile_text=str(profile.get("profile_text") or document.title),
                        status="ready",
                        extractor_model=str(profile.get("extractor_model") or ""),
                    )
                )
                await db.flush()
                job.progress = 40
                await db.commit()

                embedder = SiliconFlowProvider(settings)
                try:
                    vectors: list[list[float]] = []
                    batch_size = 32
                    for start in range(0, len(chunks), batch_size):
                        vectors.extend(
                            await embedder.embed(
                                [item.content for item in chunks[start : start + batch_size]]
                            )
                        )
                    profile_text_value = str(profile.get("profile_text") or "").strip()
                    profile_vector: list[float] | None = None
                    if profile_text_value:
                        profile_vector = (await embedder.embed([profile_text_value]))[0]
                finally:
                    await embedder.close()
            finally:
                if llm:
                    await llm.close()

            rows = [
                {
                    "chunk_id": chunk.id,
                    "notebook_id": document.notebook_id,
                    "document_id": document.id,
                    "document_version_id": version.id,
                    "section_id": chunk.section_id or "",
                    "ordinal": chunk.ordinal,
                    "title": document.title[:1024],
                    "language": version.language,
                    "page_start": chunk.page_start or 0,
                    "page_end": chunk.page_end or 0,
                    "content": chunk.content,
                    "dense": vector,
                    "is_active": True,
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            store = MilvusStore(settings)
            await asyncio.to_thread(store.upsert, rows)
            if profile_vector is not None:
                await asyncio.to_thread(
                    store.upsert_documents,
                    [
                        {
                            "profile_id": f"doc:{version.id}",
                            "notebook_id": document.notebook_id,
                            "document_id": document.id,
                            "document_version_id": version.id,
                            "title": document.title[:1024],
                            "language": version.language,
                            "text": profile_text_value,
                            "dense": profile_vector,
                            "is_active": True,
                        }
                    ],
                )

            # Text retrieval is complete; graph building runs as a separate task.
            version.status = "ready"
            version.graph_status = "pending"
            document.active_version_id = version.id
            job.status = "completed"
            job.progress = 100
            await db.commit()
            try:
                build_graph_index_task.delay(version.id)
            except Exception as exc:
                logger.warning("could not enqueue graph index for %s: %s", version.id, exc)
        except Exception as exc:
            version.status = "failed"
            version.error_message = str(exc)
            job.status = "failed"
            job.error_message = str(exc)
            await db.commit()
            raise


async def build_graph_index(document_version_id: str) -> None:
    """Build the Neo4j graph for a ready document. Never fails the document."""
    settings = get_settings()
    async with SessionFactory() as db:
        row = (
            await db.execute(
                select(DocumentVersion, Document)
                .join(Document, DocumentVersion.document_id == Document.id)
                .where(DocumentVersion.id == document_version_id)
            )
        ).one()
        version, document = row
        version.graph_status = "building"
        await db.commit()
        graph = Neo4jStore(settings)
        graph_provider = DeepSeekProvider(settings) if settings.deepseek_api_key else None
        try:
            if not await graph.verify():
                raise RuntimeError("Neo4j is unavailable")
            await graph.create_constraints()
            chunks = list(
                (
                    await db.execute(
                        select(Chunk)
                        .where(
                            Chunk.document_version_id == version.id,
                            Chunk.is_active.is_(True),
                        )
                        .order_by(Chunk.ordinal)
                    )
                )
                .scalars()
                .all()
            )
            section_titles = {
                row[0]: row[1]
                for row in (
                    await db.execute(
                        select(Section.id, Section.title).where(
                            Section.document_version_id == version.id
                        )
                    )
                ).all()
            }
            previous_chunk_id: str | None = None
            for start in range(0, len(chunks), GRAPH_BATCH_SIZE):
                batch = chunks[start : start + GRAPH_BATCH_SIZE]
                extracted = await extract_graph_batch(
                    [chunk.content for chunk in batch],
                    graph_provider,
                    settings.deepseek_model,
                )
                for chunk, (entities, relations) in zip(batch, extracted, strict=True):
                    await graph.upsert_chunk(
                        document.notebook_id,
                        version.id,
                        chunk.id,
                        {
                            "id": chunk.section_id,
                            "title": section_titles.get(chunk.section_id or "", ""),
                        },
                        entities,
                        relations,
                        previous_chunk_id,
                    )
                    previous_chunk_id = chunk.id
            version.graph_status = "ready"
            await db.commit()
        except Exception as exc:
            logger.warning("graph index failed for %s: %s", document_version_id, exc)
            version.graph_status = "failed"
            await db.commit()
        finally:
            await graph.close()
            if graph_provider:
                await graph_provider.close()


@celery_app.task(
    name="ingest_document", autoretry_for=(Exception,), retry_backoff=True, max_retries=3
)
def ingest_document_task(document_version_id: str) -> None:
    async def task_entry() -> None:
        try:
            await ingest_document_version(document_version_id)
        finally:
            # Celery invokes asyncio.run per task; discard connections bound to
            # the closing loop so the next task cannot reuse them.
            from app.core.database import engine

            await engine.dispose()

    asyncio.run(task_entry())


@celery_app.task(name="build_graph_index")
def build_graph_index_task(document_version_id: str) -> None:
    async def task_entry() -> None:
        try:
            await build_graph_index(document_version_id)
        finally:
            from app.core.database import engine

            await engine.dispose()

    asyncio.run(task_entry())
