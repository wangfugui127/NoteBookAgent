import sys
from pathlib import Path

import pytest
import yaml

from app.mcp_runtime.client_manager import McpClientManager


@pytest.mark.asyncio
async def test_stdio_mcp_discovery_and_call(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "echo_mcp_server.py"
    config = tmp_path / "mcp.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "servers": [
                    {
                        "id": "fixture",
                        "enabled": True,
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": [str(fixture)],
                        "allowed_tools": ["echo"],
                        "default_risk": "read",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manager = McpClientManager(config)
    tools = await manager.discover()
    assert manager.errors == {}
    assert [item.qualified_name for item in tools] == ["mcp.fixture.echo"]
    result = await manager.call_tool("mcp.fixture.echo", {"value": "ok"})
    assert not result["is_error"]
    assert result["content"]
