from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.models import Notebook
from app.providers.openalex import OpenAlexProvider

router = APIRouter(prefix="/notebooks/{notebook_id}/papers", tags=["papers"])


async def _owned_notebook(db: DbSession, notebook_id: str, user_id: str) -> None:
    notebook = await db.scalar(
        select(Notebook).where(Notebook.id == notebook_id, Notebook.owner_id == user_id)
    )
    if not notebook:
        raise HTTPException(404, "notebook not found")


@router.get("/search")
async def search_papers(
    notebook_id: str,
    db: DbSession,
    user: CurrentUser,
    q: str = Query(min_length=2, max_length=500),
    year_from: int | None = Query(default=None, ge=1800, le=2200),
    year_to: int | None = Query(default=None, ge=1800, le=2200),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, object]:
    await _owned_notebook(db, notebook_id, user.id)
    if year_from and year_to and year_from > year_to:
        raise HTTPException(422, "year_from must not exceed year_to")
    provider = OpenAlexProvider(get_settings())
    try:
        return {"items": await provider.search(q, year_from, year_to, limit)}
    finally:
        await provider.close()


@router.get("/{paper_id}")
async def paper_details(
    notebook_id: str, paper_id: str, db: DbSession, user: CurrentUser
) -> dict[str, object]:
    await _owned_notebook(db, notebook_id, user.id)
    provider = OpenAlexProvider(get_settings())
    try:
        return {"item": await provider.get(paper_id)}
    finally:
        await provider.close()
