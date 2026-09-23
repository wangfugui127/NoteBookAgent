from __future__ import annotations

from typing import Any

import yaml
from mcp.server import MCPServer
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.security import decode_token
from app.models import Chunk, Document, DocumentVersion, Notebook, Section
from app.providers.openalex import OpenAlexProvider
from app.providers.siliconflow import SiliconFlowProvider
from app.retrieval.milvus import MilvusStore
from app.retrieval.neo4j_store import Neo4jStore
from app.retrieval.service import RetrievalService

settings = get_settings()
mcp_server = MCPServer("NotebookAgent")


async def _authorize(access_token: str, notebook_id: str) -> str:
    payload = decode_token(access_token, "access")
    user_id = str(payload["sub"])
    async with SessionFactory() as db:
        notebook = await db.scalar(
            select(Notebook).where(Notebook.id == notebook_id, Notebook.owner_id == user_id)
        )
    if not notebook:
        raise PermissionError("notebook not found or access denied")
    return user_id


@mcp_server.tool()
async def list_notebook_sources(access_token: str, notebook_id: str) -> dict[str, Any]:
    """List documents belonging to an authorized NotebookAgent notebook."""
    await _authorize(access_token, notebook_id)
    async with SessionFactory() as db:
        rows = (
            await db.execute(
                select(Document, DocumentVersion)
                .join(
                    DocumentVersion, Document.active_version_id == DocumentVersion.id, isouter=True
                )
                .where(Document.notebook_id == notebook_id)
            )
        ).all()
    return {
        "items": [
            {
                "document_id": document.id,
                "title": document.title,
                "version_id": version.id if version else None,
                "status": version.status if version else "pending",
            }
            for document, version in rows
        ]
    }


@mcp_server.tool()
async def search_notebook(
    access_token: str,
    notebook_id: str,
    query: str,
    retrieval_mode: str = "auto",
    top_k: int = 8,
) -> dict[str, Any]:
    """Search an authorized notebook using hybrid retrieval and optional graph expansion."""
    await _authorize(access_token, notebook_id)
    service = RetrievalService(
        MilvusStore(settings), Neo4jStore(settings), SiliconFlowProvider(settings)
    )
    async with SessionFactory() as db:
        return await service.search(
            db,
            notebook_id=notebook_id,
            query=query,
            document_ids=None,
            mode=retrieval_mode,  # type: ignore[arg-type]
            top_k=min(max(top_k, 1), 20),
        )


@mcp_server.tool()
async def get_notebook_items(
    access_token: str, notebook_id: str, chunk_ids: list[str]
) -> dict[str, Any]:
    """Read exact authorized source chunks by id."""
    await _authorize(access_token, notebook_id)
    async with SessionFactory() as db:
        rows = (
            await db.execute(
                select(Chunk, DocumentVersion, Document, Section)
                .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
                .join(Document, DocumentVersion.document_id == Document.id)
                .join(Section, Chunk.section_id == Section.id, isouter=True)
                .where(
                    Chunk.id.in_(chunk_ids[:30]),
                    Chunk.is_active.is_(True),
                    Document.notebook_id == notebook_id,
                )
            )
        ).all()
    return {
        "items": [
            {
                "chunk_id": chunk.id,
                "document_version_id": version.id,
                "title": document.title,
                "section_title": section.title if section else None,
                "chunk_type": chunk.chunk_type,
                "block_ids": list(chunk.block_ids or []),
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "content": chunk.content,
            }
            for chunk, version, document, section in rows
        ]
    }


@mcp_server.tool()
async def search_papers(
    access_token: str, notebook_id: str, query: str, limit: int = 10
) -> dict[str, Any]:
    """Search OpenAlex after checking the caller can access the notebook scope."""
    await _authorize(access_token, notebook_id)
    return {"items": await OpenAlexProvider(settings).search(query, limit=min(limit, 30))}


@mcp_server.tool()
async def get_paper_details(access_token: str, notebook_id: str, paper_id: str) -> dict[str, Any]:
    """Get one OpenAlex paper after checking the notebook scope."""
    await _authorize(access_token, notebook_id)
    return {"item": await OpenAlexProvider(settings).get(paper_id)}


mcp_http_app = mcp_server.streamable_http_app()

# The server code contains the five safe handlers, while this file decides which
# of them are actually visible from the operator-owned allowlist.
expose_config = yaml.safe_load(settings.mcp_expose_config.read_text(encoding="utf-8")) or {}
allowed_tools = set(expose_config.get("allowed_tools") or [])
if not expose_config.get("enabled", True):
    allowed_tools = set()
for registered in list(mcp_server._tool_manager.list_tools()):
    if registered.name not in allowed_tools:
        mcp_server.remove_tool(registered.name)
