from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import CurrentUser

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/mcp")
async def mcp_status(request: Request, _user: CurrentUser) -> dict[str, object]:
    manager = request.app.state.mcp_manager
    return {
        "servers": [
            {"id": item.id, "enabled": item.enabled, "transport": item.transport}
            for item in manager.servers.values()
        ],
        "tools": sorted(manager.tools),
        "errors": manager.errors,
    }


@router.post("/mcp/reload")
async def reload_mcp(request: Request, _user: CurrentUser) -> dict[str, object]:
    manager = request.app.state.mcp_manager
    tools = await manager.discover()
    return {"tools": [item.qualified_name for item in tools], "errors": manager.errors}


@router.post("/mcp/{server_id}/test")
async def test_mcp(server_id: str, request: Request, _user: CurrentUser) -> dict[str, object]:
    manager = request.app.state.mcp_manager
    await manager.discover()
    if server_id not in manager.servers:
        raise HTTPException(404, "MCP server not found")
    return {"ok": server_id not in manager.errors, "error": manager.errors.get(server_id)}


@router.get("/skills")
async def skills_status(request: Request, _user: CurrentUser) -> dict[str, object]:
    return {"items": request.app.state.skill_catalog.summaries()}


@router.post("/skills/reload")
async def reload_skills(request: Request, _user: CurrentUser) -> dict[str, object]:
    catalog = request.app.state.skill_catalog
    items = catalog.reload(request.app.state.known_tools)
    return {"items": [item.summary() for item in items]}
