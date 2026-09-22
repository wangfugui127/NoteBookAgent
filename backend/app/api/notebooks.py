from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import func, select

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.ingestion.tasks import ingest_document_task
from app.models import Document, DocumentVersion, IngestionJob, Notebook
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
    document = Document(
        notebook_id=notebook_id,
        title=file.filename or "untitled",
        media_type=file.content_type or "application/octet-stream",
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
    suffix = Path(file.filename or "upload").suffix
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
    return {"document_id": document.id, "version_id": version.id, "job_id": job.id}
