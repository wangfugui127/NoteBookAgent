from __future__ import annotations

import asyncio

from app.agent.runtime import AgentRuntime
from app.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import SessionFactory
from app.mcp_runtime.client_manager import McpClientManager


async def execute_run(run_id: str) -> None:
    settings = get_settings()
    mcp = McpClientManager(settings.mcp_servers_config)
    await mcp.discover()
    runtime = AgentRuntime(settings, mcp)
    try:
        async with SessionFactory() as db:
            await runtime.execute(db, run_id)
    finally:
        await runtime.close()


@celery_app.task(
    name="execute_agent_run", autoretry_for=(Exception,), retry_backoff=True, max_retries=2
)
def execute_agent_run_task(run_id: str) -> None:
    async def task_entry() -> None:
        try:
            await execute_run(run_id)
        finally:
            from app.core.database import engine

            await engine.dispose()

    asyncio.run(task_entry())
