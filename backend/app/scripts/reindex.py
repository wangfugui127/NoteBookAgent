"""Rebuild Milvus (chunk v2 + document profiles) from the MySQL source of truth."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.models import Chunk, Document, DocumentProfile, DocumentVersion
from app.providers.siliconflow import SiliconFlowProvider
from app.retrieval.milvus import MilvusStore


async def reindex() -> None:
    settings = get_settings()
    embedder = SiliconFlowProvider(settings)
    store = MilvusStore(settings)
    try:
        async with SessionFactory() as db:
            rows = (
                await db.execute(
                    select(Document, DocumentVersion)
                    .join(DocumentVersion, Document.active_version_id == DocumentVersion.id)
                    .where(DocumentVersion.status == "ready")
                )
            ).all()
            for document, version in rows:
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
                if chunks:
                    vectors: list[list[float]] = []
                    batch_size = 32
                    for start in range(0, len(chunks), batch_size):
                        vectors.extend(
                            await embedder.embed(
                                [item.content for item in chunks[start : start + batch_size]]
                            )
                        )
                    await asyncio.to_thread(
                        store.upsert,
                        [
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
                                "chunk_type": chunk.chunk_type,
                                "block_ids": list(chunk.block_ids or []),
                                "content": chunk.content,
                                "dense": vector,
                                "is_active": True,
                            }
                            for chunk, vector in zip(chunks, vectors, strict=True)
                        ],
                    )
                profile = await db.scalar(
                    select(DocumentProfile).where(
                        DocumentProfile.document_version_id == version.id
                    )
                )
                if profile and profile.profile_text:
                    profile_vector = (await embedder.embed([profile.profile_text]))[0]
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
                                "text": profile.profile_text,
                                "dense": profile_vector,
                                "is_active": True,
                            }
                        ],
                    )
                print(f"reindexed {document.title} ({len(chunks)} chunks)")
    finally:
        await embedder.close()


def main() -> None:
    asyncio.run(reindex())


if __name__ == "__main__":
    main()
