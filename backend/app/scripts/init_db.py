import asyncio

from sqlalchemy import inspect, text

from app.core.database import engine
from app.models import Base


def _add_missing_columns(sync_connection) -> None:
    """create_all only creates missing tables; patch pre-existing tables here."""
    inspector = inspect(sync_connection)
    if inspector.has_table("evidence"):
        columns = {column["name"] for column in inspector.get_columns("evidence")}
        if "section_title" not in columns:
            sync_connection.execute(
                text("ALTER TABLE evidence ADD COLUMN section_title VARCHAR(512) NULL")
            )
    if inspector.has_table("document_versions"):
        columns = {column["name"] for column in inspector.get_columns("document_versions")}
        if "graph_status" not in columns:
            sync_connection.execute(
                text(
                    "ALTER TABLE document_versions "
                    "ADD COLUMN graph_status VARCHAR(24) NOT NULL DEFAULT 'pending'"
                )
            )
    if inspector.has_table("users"):
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "approval_mode" not in columns:
            sync_connection.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN approval_mode VARCHAR(16) NOT NULL DEFAULT 'confirm'"
                )
            )
    if inspector.has_table("approval_requests"):
        columns = {column["name"] for column in inspector.get_columns("approval_requests")}
        if "mode" not in columns:
            sync_connection.execute(
                text(
                    "ALTER TABLE approval_requests "
                    "ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'confirm'"
                )
            )
        if "tool_risk" not in columns:
            sync_connection.execute(
                text(
                    "ALTER TABLE approval_requests "
                    "ADD COLUMN tool_risk VARCHAR(16) NOT NULL DEFAULT 'write'"
                )
            )


async def main() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_add_missing_columns)


if __name__ == "__main__":
    asyncio.run(main())
