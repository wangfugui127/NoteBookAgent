from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.models import Notebook
from app.providers.siliconflow import SiliconFlowProvider
from app.retrieval.milvus import MilvusStore
from app.retrieval.neo4j_store import Neo4jStore
from app.retrieval.service import RetrievalService

router = APIRouter(prefix="/notebooks/{notebook_id}/graph", tags=["graph"])


async def _owned_notebook(db: DbSession, notebook_id: str, user_id: str) -> None:
    notebook = await db.scalar(
        select(Notebook).where(Notebook.id == notebook_id, Notebook.owner_id == user_id)
    )
    if not notebook:
        raise HTTPException(404, "notebook not found")


@router.get("/experiments")
async def graph_experiments(
    notebook_id: str,
    db: DbSession,
    user: CurrentUser,
    q: str = Query(default="", max_length=500),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, object]:
    """Debug/visualization view of Paper -> Experiment -> Method/Dataset/Result evidence."""
    await _owned_notebook(db, notebook_id, user.id)
    settings = get_settings()
    service = RetrievalService(
        MilvusStore(settings), Neo4jStore(settings), SiliconFlowProvider(settings)
    )
    try:
        return await service.graph_experiments(
            db, notebook_id=notebook_id, query=q, limit=limit
        )
    finally:
        await service.close()
