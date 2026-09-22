import pytest

from app.agent.router import DefaultRouterProvider
from app.agent.types import ToolSummary
from app.tools.native import build_native_registry


@pytest.mark.asyncio
async def test_router_selects_relevant_tools_and_caps_count() -> None:
    catalog = [
        ToolSummary(name=f"tool_{index}", description=f"能力 {index}", risk="read")
        for index in range(20)
    ]
    catalog.append(ToolSummary("search_notebook", "检索论文证据", "read"))
    selected = await DefaultRouterProvider().select_tools("请检索论文证据", catalog, 12)
    assert "search_notebook" in selected
    assert len(selected) <= 12


def test_unknown_and_write_mcp_tools_require_approval() -> None:
    registry = build_native_registry()
    assert registry.requires_approval("missing-tool")
    assert not registry.requires_approval("search_notebook")
    assert len(registry.schemas(list(registry.definitions))) == 9


def test_provider_alias_keeps_dotted_mcp_name_internal() -> None:
    registry = build_native_registry()
    alias = registry.provider_name("mcp.example.search")
    assert alias == "mcp__example__search"
    registry.definitions["mcp.example.search"] = registry.definitions["search_notebook"]
    assert registry.resolve_provider_name(alias) == "mcp.example.search"
