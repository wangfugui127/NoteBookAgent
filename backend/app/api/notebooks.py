from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from sqlalchemy import delete, select

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.ingestion.sources import create_source, delete_source
from app.models import Document, DocumentVersion, Notebook
from app.retrieval.milvus import MilvusStore
from app.retrieval.neo4j_store import Neo4jStore
from app.schemas import NotebookCreate, NotebookUpdate, NotebookView

router = APIRouter(prefix="/notebooks", tags=["notebooks"])


async def owned_notebook(db: DbSession, notebook_id: str, user_id: str) -> Notebook:
    notebook = await db.scalar(
        select(Notebook).where(Notebook.id == notebook_id, Notebook.owner_id == user_id)
    )
    if not notebook:
        raise HTTPException(404, "notebook not found")
    return notebook


@router.get("", response_model=list[NotebookView])
async def list_notebooks(db: DbSession, user: CurrentUser) -> list[Notebook]:
    return list((await db.execute(select(Notebook).where(Notebook.owner_id == user.id))).scalars())


@router.post("", response_model=NotebookView, status_code=201)
async def create_notebook(payload: NotebookCreate, db: DbSession, user: CurrentUser) -> Notebook:
    notebook = Notebook(owner_id=user.id, **payload.model_dump())
    db.add(notebook)
    await db.commit()
    await db.refresh(notebook)
    return notebook


@router.patch("/{notebook_id}", response_model=NotebookView)
async def update_notebook(
    notebook_id: str, payload: NotebookUpdate, db: DbSession, user: CurrentUser
) -> Notebook:
    notebook = await owned_notebook(db, notebook_id, user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(notebook, key, value)
    await db.commit()
    return notebook


@router.delete("/{notebook_id}", status_code=204)
async def delete_notebook(notebook_id: str, db: DbSession, user: CurrentUser) -> Response:
    await owned_notebook(db, notebook_id, user.id)
    settings = get_settings()
    milvus: MilvusStore | None = None
    neo4j: Neo4jStore | None = None
    try:
        milvus = MilvusStore(settings)
        neo4j = Neo4jStore(settings)
    except Exception:
        milvus, neo4j = None, None
    retrieval = SimpleNamespace(milvus=milvus, neo4j=neo4j)
    try:
        documents = (
            (await db.execute(select(Document).where(Document.notebook_id == notebook_id)))
            .scalars()
            .all()
        )
        for document in documents:
            await delete_source(db, retrieval, document, settings)
        await db.execute(delete(Notebook).where(Notebook.id == notebook_id))
        await db.commit()
    finally:
        if neo4j is not None:
            try:
                await neo4j.close()
            except Exception:
                pass
        close = getattr(getattr(milvus, "client", None), "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    shutil.rmtree(Path(settings.upload_dir) / notebook_id, ignore_errors=True)
    return Response(status_code=204)


@router.get("/{notebook_id}/documents")
async def list_documents(notebook_id: str, db: DbSession, user: CurrentUser) -> dict[str, object]:
    await owned_notebook(db, notebook_id, user.id)
    rows = (
        await db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, Document.active_version_id == DocumentVersion.id, isouter=True)
            .where(Document.notebook_id == notebook_id)
        )
    ).all()
    return {
        "items": [
            {
                "id": document.id,
                "title": document.title,
                "media_type": document.media_type,
                "version_id": version.id if version else None,
                "status": version.status if version else "pending",
                "graph_status": version.graph_status if version else "pending",
                "error_message": version.error_message if version else None,
            }
            for document, version in rows
        ]
    }


@router.post("/{notebook_id}/documents", status_code=202)
async def upload_document(
    notebook_id: str,
    db: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> dict[str, str]:
    await owned_notebook(db, notebook_id, user.id)
    settings = get_settings()
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(413, "file exceeds 100 MB")
    suffix = Path(file.filename or "upload").suffix
    document, version, job = await create_source(
        db,
        settings,
        notebook_id=notebook_id,
        title=file.filename or "untitled",
        media_type=file.content_type or "application/octet-stream",
        content=content,
        suffix=suffix,
    )
    return {"document_id": document.id, "version_id": version.id, "job_id": job.id}
