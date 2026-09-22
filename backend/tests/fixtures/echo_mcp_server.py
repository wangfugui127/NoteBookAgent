from mcp.server import MCPServer

server = MCPServer("NotebookAgent MCP fixture")


@server.tool()
async def echo(value: str) -> dict[str, str]:
    """Return a value for MCP discovery and call integration tests."""
    return {"value": value}


if __name__ == "__main__":
    server.run(transport="stdio")
