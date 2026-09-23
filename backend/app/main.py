from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agent_runs,
    auth,
    conversations,
    notebooks,
    papers,
    runtime_config,
    users,
)
from app.core.config import get_settings
from app.mcp_runtime.client_manager import McpClientManager
from app.mcp_runtime.server import mcp_http_app, mcp_server
from app.skills.catalog import SkillCatalog
from app.tools.native import build_native_registry

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = McpClientManager(settings.mcp_servers_config)
    await manager.discover()
    native = build_native_registry()
    native.register_mcp(list(manager.tools.values()))
    catalog = SkillCatalog(settings.skills_config)
    catalog.reload(set(native.definitions))
    app.state.mcp_manager = manager
    app.state.skill_catalog = catalog
    app.state.known_tools = set(native.definitions)
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


for router in (
    auth.router,
    users.router,
    notebooks.router,
    conversations.router,
    papers.router,
    agent_runs.router,
    runtime_config.router,
):
    app.include_router(router, prefix="/api/v1")

app.mount("/", mcp_http_app)
