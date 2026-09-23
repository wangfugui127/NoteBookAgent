from __future__ import annotations

import asyncio

from app.agent.runtime import AgentRuntime
from app.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import SessionFactory
from app.evaluation.service import execute_evaluation
from app.mcp_runtime.client_manager import McpClientManager


async def run_evaluation(eval_run_id: str) -> None:
    settings = get_settings()
    mcp = McpClientManager(settings.mcp_servers_config)
    await mcp.discover()
    runtime = AgentRuntime(settings, mcp)
    try:
        async with SessionFactory() as db:
            await execute_evaluation(db, eval_run_id, runtime)
    finally:
        await runtime.close()


@celery_app.task(name="execute_evaluation", max_retries=0)
def execute_evaluation_task(eval_run_id: str) -> None:
    async def task_entry() -> None:
        try:
            await run_evaluation(eval_run_id)
        finally:
            from app.core.database import engine

            await engine.dispose()

    asyncio.run(task_entry())
