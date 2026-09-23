from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.ingestion.tasks import ingest_document_task
from app.models import (
    Chunk,
    Citation,
    Document,
    DocumentVersion,
    Evidence,
    IngestionJob,
)


async def create_source(
    db: AsyncSession,
    settings: Settings,
    *,
    notebook_id: str,
    title: str,
    media_type: str,
    content: bytes,
    suffix: str,
) -> tuple[Document, DocumentVersion, IngestionJob]:
    """Persist a source file and enqueue ingestion. Shared by upload and tools."""
    document = Document(
        notebook_id=notebook_id,
        title=(title or "untitled")[:512],
        media_type=media_type,
    )
    db.add(document)
    await db.flush()
    version_number = (
        int(
            await db.scalar(
                select(func.count(DocumentVersion.id)).where(
                    DocumentVersion.document_id == document.id
                )
            )
            or 0
        )
        + 1
    )
    target_dir = Path(settings.upload_dir) / notebook_id / document.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"v{version_number}{suffix}"
    target.write_bytes(content)
    version = DocumentVersion(
        document_id=document.id,
        version_number=version_number,
        storage_path=str(target),
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(version)
    await db.flush()
    job = IngestionJob(
        document_version_id=version.id,
        idempotency_key=f"ingest:{version.id}:{version.content_hash}",
    )
    db.add(job)
    await db.commit()
    ingest_document_task.delay(version.id)
    return document, version, job


async def delete_source(
    db: AsyncSession,
    retrieval: Any,
    document: Document,
    settings: Settings | None = None,
) -> None:
    """Delete one source and its derived rows/index entries. Shared by tool and API."""
    versions = (
        (
            await db.execute(
                select(DocumentVersion).where(DocumentVersion.document_id == document.id)
            )
        )
        .scalars()
        .all()
    )
    for version in versions:
        chunk_ids = (
            (
                await db.execute(select(Chunk.id).where(Chunk.document_version_id == version.id))
            )
            .scalars()
            .all()
        )
        if chunk_ids:
            evidence_ids = (
                (
                    await db.execute(
                        select(Evidence.id).where(Evidence.chunk_id.in_(list(chunk_ids)))
                    )
                )
                .scalars()
                .all()
            )
            if evidence_ids:
                await db.execute(
                    delete(Citation).where(Citation.evidence_id.in_(list(evidence_ids)))
                )
                await db.execute(delete(Evidence).where(Evidence.id.in_(list(evidence_ids))))
        try:
            await retrieval.neo4j.delete_document_version(version.id)
        except Exception:
            pass
    await db.execute(delete(Document).where(Document.id == document.id))
    await db.commit()
    try:
        await asyncio.to_thread(retrieval.milvus.delete_by_document, document.id)
    except Exception:
        pass
    if settings is not None:
        target = Path(settings.upload_dir) / document.notebook_id / document.id
        shutil.rmtree(target, ignore_errors=True)
