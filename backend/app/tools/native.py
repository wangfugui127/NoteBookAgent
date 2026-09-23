from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.ingestion.sources import create_source, delete_source
from app.models import (
    Chunk,
    Document,
    DocumentVersion,
    ExternalPaperResult,
    TaskItem,
)
from app.tools.registry import ToolDefinition, ToolExecutionContext, ToolRegistry


class TaskUpdateArgs(BaseModel):
    tasks: list[dict[str, Any]] = Field(max_length=30)


class ListSourcesArgs(BaseModel):
    limit: int = Field(default=30, ge=1, le=100)


class SearchNotebookArgs(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=20)
    retrieval_mode: Literal[
        "hybrid", "hybrid_graph", "layered", "auto", "comprehensive"
    ] = "auto"


class GetItemsArgs(BaseModel):
    chunk_ids: list[str] = Field(min_length=1, max_length=30)
    context_window: int = Field(default=0, ge=0, le=2)


class SearchPapersArgs(BaseModel):
    query: str
    year_from: int | None = None
    year_to: int | None = None
    limit: int = Field(default=10, ge=1, le=30)


class PaperDetailsArgs(BaseModel):
    paper_id: str


class LoadSkillArgs(BaseModel):
    name: str


class ToolSearchArgs(BaseModel):
    query: str
    limit: int = Field(default=12, ge=1, le=12)


class ReadMcpResourceArgs(BaseModel):
    server_id: str
    uri: str


class AddPapersArgs(BaseModel):
    paper_ids: list[str] = Field(min_length=1, max_length=10)
    instruction: str = ""


class RemoveSourcesArgs(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=20)


async def task_update(args: TaskUpdateArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    await ctx.db.execute(delete(TaskItem).where(TaskItem.run_id == ctx.state.run_id))
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(args.tasks):
        value = {
            "title": str(item.get("title") or "")[:512],
            "status": str(item.get("status") or "pending"),
        }
        ctx.db.add(TaskItem(run_id=ctx.state.run_id, ordinal=index, **value))
        normalized.append(value)
    ctx.state.tasks = normalized
    await ctx.db.flush()
    return {"tasks": normalized}


async def list_sources(args: ListSourcesArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    rows = (
        await ctx.db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, Document.active_version_id == DocumentVersion.id, isouter=True)
            .where(Document.notebook_id == ctx.state.notebook_id)
            .limit(args.limit)
        )
    ).all()
    return {
        "items": [
            {
                "document_id": document.id,
                "title": document.title,
                "media_type": document.media_type,
                "version_id": version.id if version else None,
                "status": version.status if version else "pending",
            }
            for document, version in rows
        ]
    }


async def search_notebook(args: SearchNotebookArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    result = await ctx.retrieval.search(
        ctx.db,
        notebook_id=ctx.state.notebook_id,
        query=args.query,
        document_ids=ctx.allowed_document_ids,
        mode=args.retrieval_mode,
        top_k=args.top_k,
    )
    ctx.state.graph_degraded = bool(result["graph_degraded"])
    return result


async def get_items(args: GetItemsArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    requested = set(args.chunk_ids)
    rows = (
        await ctx.db.execute(
            select(Chunk, DocumentVersion, Document)
            .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(
                Chunk.id.in_(requested),
                Chunk.is_active.is_(True),
                Document.notebook_id == ctx.state.notebook_id,
            )
        )
    ).all()
    return {
        "items": [
            {
                "chunk_id": chunk.id,
                "document_version_id": version.id,
                "document_id": document.id,
                "title": document.title,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "content": chunk.content,
            }
            for chunk, version, document in rows
            if ctx.allowed_document_ids is None or document.id in ctx.allowed_document_ids
        ]
    }


async def search_papers(args: SearchPapersArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    return {
        "items": await ctx.openalex.search(args.query, args.year_from, args.year_to, args.limit),
        "persisted_to_notebook": False,
    }


async def paper_details(args: PaperDetailsArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    return {"item": await ctx.openalex.get(args.paper_id), "persisted_to_notebook": False}


async def load_skill(args: LoadSkillArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    allowed = set(ctx.registry.definitions)
    loaded = ctx.skills.load(args.name, allowed)
    ctx.state.loaded_skills[args.name] = loaded["version"]
    ctx.state.active_tool_allowlist = list(loaded["allowed_tools"])
    return loaded


async def tool_search(args: ToolSearchArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    query_words = set(args.query.lower().split())
    scored: list[tuple[int, str, str, str]] = []
    for item in ctx.registry.summaries():
        haystack = f"{item.name} {item.description}".lower()
        score = sum(1 for word in query_words if word in haystack)
        scored.append((score, item.name, item.description, item.risk))
    scored.sort(key=lambda value: (-value[0], value[1]))
    return {
        "tools": [
            {"name": name, "description": description, "risk": risk}
            for _, name, description, risk in scored[: args.limit]
        ]
    }


async def read_mcp_resource(args: ReadMcpResourceArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    return await ctx.mcp.read_resource(args.server_id, args.uri)


def _paper_markdown(detail: dict[str, Any]) -> str:
    authors = ", ".join(detail.get("authors") or [])
    lines = [
        f"# {detail.get('title') or 'Untitled'}",
        f"Authors: {authors or 'unknown'}",
        f"Year: {detail.get('year') or 'unknown'}",
        f"OpenAlex ID: {detail.get('paper_id') or ''}",
        f"DOI: {detail.get('doi') or 'n/a'}",
        f"URL: {detail.get('url') or 'n/a'}",
        "",
        "## Abstract",
        str(detail.get("abstract") or "OpenAlex did not provide an abstract for this paper."),
        "",
        "> 本来源仅包含外部元数据与摘要，不是论文全文。",
    ]
    return "\n".join(lines)


async def _fetch_pdf(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        content = response.content
        if not (content[:5] == b"%PDF-" or url.lower().endswith(".pdf")):
            raise ValueError("downloaded content is not a PDF")
        return content


async def add_papers(args: AddPapersArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for paper_id in args.paper_ids:
        detail = await ctx.openalex.get(paper_id)
        title = str(detail.get("title") or paper_id)
        content: bytes | None = None
        media_type = "text/markdown"
        suffix = ".md"
        imported_as = "metadata"
        pdf_url = detail.get("pdf_url")
        if pdf_url:
            try:
                content = await _fetch_pdf(str(pdf_url))
                media_type = "application/pdf"
                suffix = ".pdf"
                imported_as = "pdf"
            except Exception:
                content = None
        if content is None:
            content = _paper_markdown(detail).encode("utf-8")
        document, version, job = await create_source(
            ctx.db,
            ctx.settings,
            notebook_id=ctx.state.notebook_id,
            title=title,
            media_type=media_type,
            content=content,
            suffix=suffix,
        )
        ctx.db.add(
            ExternalPaperResult(
                run_id=ctx.state.run_id,
                provider="openalex",
                provider_paper_id=paper_id,
                data=detail,
            )
        )
        await ctx.db.commit()
        items.append(
            {
                "document_id": document.id,
                "version_id": version.id,
                "job_id": job.id,
                "title": title,
                "imported_as": imported_as,
            }
        )
    return {"items": items, "persisted_to_notebook": True}


async def remove_sources(args: RemoveSourcesArgs, ctx: ToolExecutionContext) -> dict[str, Any]:
    removed: list[str] = []
    not_found: list[str] = []
    for document_id in args.document_ids:
        document = await ctx.db.scalar(
            select(Document).where(
                Document.id == document_id, Document.notebook_id == ctx.state.notebook_id
            )
        )
        if not document:
            not_found.append(document_id)
            continue
        await delete_source(ctx.db, ctx.retrieval, document, ctx.settings)
        removed.append(document.id)
    return {"removed": removed, "not_found": not_found}


def build_native_registry() -> ToolRegistry:
    registry = ToolRegistry()
    definitions = [
        ("task_update", "更新当前 Agent Run 的任务清单。", TaskUpdateArgs, "read", task_update),
        (
            "list_notebook_sources",
            "列出当前 Notebook 的资料与处理状态。",
            ListSourcesArgs,
            "read",
            list_sources,
        ),
        (
            "search_notebook",
            "在当前 Notebook 执行 Dense、BM25 与可选 GraphRAG 检索。",
            SearchNotebookArgs,
            "read",
            search_notebook,
        ),
        (
            "get_notebook_items",
            "按 chunk_id 读取当前 Notebook 的精确原文。",
            GetItemsArgs,
            "read",
            get_items,
        ),
        (
            "search_papers",
            "通过 OpenAlex 搜索外部论文，不写入 Notebook。",
            SearchPapersArgs,
            "read",
            search_papers,
        ),
        (
            "get_paper_details",
            "读取 OpenAlex 论文详情，不写入 Notebook。",
            PaperDetailsArgs,
            "read",
            paper_details,
        ),
        (
            "add_paper_to_notebook",
            "把 OpenAlex 外部论文加入当前 Notebook（有开放获取PDF则抓取全文，"
            "否则加入摘要与元数据）。",
            AddPapersArgs,
            "write",
            add_papers,
        ),
        (
            "remove_notebook_source",
            "从当前 Notebook 删除指定来源及其检索索引。",
            RemoveSourcesArgs,
            "destructive",
            remove_sources,
        ),
        (
            "load_skill",
            "按名称加载完整 Skill 指令，Skill 不能扩大权限。",
            LoadSkillArgs,
            "read",
            load_skill,
        ),
        (
            "tool_search",
            "搜索短工具目录，最多返回 12 个候选。",
            ToolSearchArgs,
            "read",
            tool_search,
        ),
        (
            "read_mcp_resource",
            "读取已配置 MCP Server 的资源。",
            ReadMcpResourceArgs,
            "read",
            read_mcp_resource,
        ),
    ]
    for name, description, model, risk, handler in definitions:
        registry.register(ToolDefinition(name, description, model, risk, handler))
    return registry
