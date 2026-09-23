from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.agent.types import AgentState, ToolObservation, ToolSummary

ToolHandler = Callable[[BaseModel, "ToolExecutionContext"], Awaitable[dict[str, Any]]]

ApprovalMode = Literal["read_only", "confirm", "auto"]
PermissionDecision = Literal["allow", "approve", "deny"]


@dataclass(slots=True)
class ToolExecutionContext:
    db: Any
    settings: Any
    state: AgentState
    retrieval: Any
    openalex: Any
    skills: Any
    mcp: Any
    registry: ToolRegistry
    allowed_document_ids: list[str] | None = None


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    arguments_model: type[BaseModel] | None
    risk: str
    handler: ToolHandler | None
    source: str = "native"
    raw_schema: dict[str, Any] | None = None

    def summary(self) -> ToolSummary:
        return ToolSummary(
            name=self.name,
            description=self.description,
            risk=self.risk,  # type: ignore[arg-type]
            source=self.source,
        )

    def provider_schema(self, provider_name: str | None = None) -> dict[str, Any]:
        parameters = self.raw_schema or (
            self.arguments_model.model_json_schema() if self.arguments_model else {"type": "object"}
        )
        return {
            "type": "function",
            "function": {
                "name": provider_name or self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self.definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self.definitions:
            raise ValueError(f"duplicate tool: {definition.name}")
        self.definitions[definition.name] = definition

    def register_mcp(self, tools: list[Any]) -> None:
        self.definitions = {
            name: item for name, item in self.definitions.items() if item.source != "mcp"
        }
        for tool in tools:
            self.register(
                ToolDefinition(
                    name=tool.qualified_name,
                    description=tool.description,
                    arguments_model=None,
                    risk=tool.risk,
                    handler=None,
                    source="mcp",
                    raw_schema=tool.input_schema,
                )
            )

    def summaries(self) -> list[ToolSummary]:
        return [item.summary() for item in self.definitions.values()]

    @staticmethod
    def provider_name(name: str) -> str:
        alias = name.replace(".", "__")
        if len(alias) <= 64:
            return alias
        digest = hashlib.sha256(name.encode()).hexdigest()[:8]
        return f"{alias[:55]}_{digest}"

    def resolve_provider_name(self, provider_name: str) -> str:
        for canonical in self.definitions:
            if self.provider_name(canonical) == provider_name:
                return canonical
        return provider_name

    def schemas(self, names: list[str]) -> list[dict[str, Any]]:
        return [
            self.definitions[name].provider_schema(self.provider_name(name))
            for name in names
            if name in self.definitions
        ]

    @staticmethod
    def arguments_hash(name: str, arguments: dict[str, Any]) -> str:
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{name}:{canonical}".encode()).hexdigest()

    def requires_approval(self, name: str) -> bool:
        definition = self.definitions.get(name)
        return not definition or definition.risk in {"write", "destructive"}

    def decide(self, name: str, mode: str = "confirm") -> PermissionDecision:
        """Combine tool risk with the user-selected approval mode."""
        definition = self.definitions.get(name)
        risk = definition.risk if definition else "write"
        if risk == "read":
            return "allow"
        if mode == "auto":
            return "allow"
        if mode == "read_only":
            return "deny"
        return "approve"

    async def dispatch(
        self, name: str, arguments: dict[str, Any], context: ToolExecutionContext
    ) -> ToolObservation:
        definition = self.definitions.get(name)
        if not definition:
            return ToolObservation(False, name, {}, "tool_not_found")
        try:
            if definition.source == "mcp":
                result = await context.mcp.call_tool(name, arguments)
            else:
                assert definition.arguments_model is not None and definition.handler is not None
                parsed = definition.arguments_model.model_validate(arguments)
                result = await definition.handler(parsed, context)
            encoded = json.dumps(result, ensure_ascii=False, default=str)
            truncated = len(encoded) > 40_000
            if truncated:
                result = {"truncated": True, "preview": encoded[:40_000]}
            return ToolObservation(True, name, result, truncated=truncated)
        except ValidationError as exc:
            return ToolObservation(False, name, {"details": exc.errors()}, "invalid_arguments")
        except Exception as exc:
            return ToolObservation(False, name, {"message": str(exc)}, "tool_error")
