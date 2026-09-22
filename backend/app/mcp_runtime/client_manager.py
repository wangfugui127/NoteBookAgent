from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")


def _expand(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, str):
        match = ENV_PATTERN.match(value)
        if match:
            return os.getenv(match.group(1), "")
    return value


@dataclass(slots=True)
class McpTool:
    server_id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: str

    @property
    def qualified_name(self) -> str:
        return f"mcp.{self.server_id}.{self.name}"


@dataclass(slots=True)
class McpServerConfig:
    id: str
    enabled: bool
    transport: str
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    auth_token: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    default_risk: str = "write"


class McpClientManager:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.servers: dict[str, McpServerConfig] = {}
        self.tools: dict[str, McpTool] = {}
        self.errors: dict[str, str] = {}

    def load_config(self) -> list[McpServerConfig]:
        raw = _expand(yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {})
        servers: dict[str, McpServerConfig] = {}
        for item in raw.get("servers") or []:
            server_id = str(item["id"])
            if server_id in servers:
                raise ValueError(f"duplicate MCP server id: {server_id}")
            transport = str(item.get("transport") or "")
            if transport not in {"stdio", "streamable_http"}:
                raise ValueError(f"unsupported MCP transport for {server_id}: {transport}")
            token_env = str(item.get("auth_env") or "")
            servers[server_id] = McpServerConfig(
                id=server_id,
                enabled=bool(item.get("enabled", True)),
                transport=transport,
                url=item.get("url"),
                command=item.get("command"),
                args=[str(value) for value in item.get("args") or []],
                env={str(key): str(value) for key, value in (item.get("env") or {}).items()},
                auth_token=os.getenv(token_env, "") if token_env else "",
                allowed_tools=[str(value) for value in item.get("allowed_tools") or []],
                default_risk=str(item.get("default_risk") or "write"),
            )
        self.servers = servers
        return list(servers.values())

    def _client(self, server: McpServerConfig) -> Any:
        from mcp import Client, StdioServerParameters

        if server.transport == "streamable_http":
            if not server.url:
                raise ValueError(f"MCP server {server.id} has no url")
            if not server.auth_token:
                return Client(server.url)
            import httpx2
            from mcp.client.streamable_http import streamable_http_client

            @asynccontextmanager
            async def authenticated_transport():
                async with httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {server.auth_token}"}
                ) as http_client:
                    async with streamable_http_client(
                        server.url, http_client=http_client
                    ) as streams:
                        yield streams

            return Client(authenticated_transport())
        if not server.command:
            raise ValueError(f"MCP server {server.id} has no command")
        parameters = StdioServerParameters(
            command=server.command, args=server.args, env=server.env or None
        )
        return Client(parameters)

    async def discover(self) -> list[McpTool]:
        self.load_config()
        self.tools = {}
        self.errors = {}
        for server in self.servers.values():
            if not server.enabled:
                continue
            try:
                async with self._client(server) as client:
                    result = await client.list_tools()
                for item in result.tools:
                    if server.allowed_tools and item.name not in server.allowed_tools:
                        continue
                    risk_map = getattr(item, "annotations", None)
                    read_only = bool(getattr(risk_map, "read_only_hint", False))
                    risk = "read" if read_only else server.default_risk
                    tool = McpTool(
                        server_id=server.id,
                        name=item.name,
                        description=item.description or "External MCP tool",
                        input_schema=dict(item.input_schema or {"type": "object"}),
                        risk=risk if risk in {"read", "write", "destructive"} else "write",
                    )
                    self.tools[tool.qualified_name] = tool
            except Exception as exc:
                self.errors[server.id] = str(exc)
        return list(self.tools.values())

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(qualified_name)
        if not tool:
            raise KeyError(f"unknown MCP tool: {qualified_name}")
        server = self.servers[tool.server_id]
        async with self._client(server) as client:
            result = await client.call_tool(tool.name, arguments)
        content = [item.model_dump(mode="json") for item in result.content]
        return {"content": content, "is_error": bool(getattr(result, "is_error", False))}

    async def read_resource(self, server_id: str, uri: str) -> dict[str, Any]:
        server = self.servers.get(server_id)
        if not server or not server.enabled:
            raise KeyError(f"unknown MCP server: {server_id}")
        async with self._client(server) as client:
            result = await client.read_resource(uri)
        return {"contents": [item.model_dump(mode="json") for item in result.contents]}
