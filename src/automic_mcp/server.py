"""Stage 2: FastMCP server with read-only tools backed by the real Automic
AE REST API (search, get a single object, ping/connectivity check).

The stage-1 mock tool has been removed now that we have real read tools -
keeping a fake tool alongside real ones risked confusing whichever client
(human or LLM) picks a tool to call.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from automic_mcp.automic_client import AutomicClient

mcp = FastMCP(
    "automic-mcp-server",
    instructions=(
        "MCP server for the Broadcom Automic Automation Engine. Stage 2: "
        "read-only tools for querying AE objects (jobs, workflows, etc.). "
        "No object is ever created, modified, deleted, or executed by these tools."
    ),
)


@mcp.tool()
async def ping_automic() -> dict[str, str]:
    """Check whether the Automic AE REST API is reachable and responding."""
    async with AutomicClient() as client:
        await client.ping()
    return {"status": "ok"}


@mcp.tool()
async def search_objects(
    object_name: str | None = None,
    object_types: list[str] | None = None,
    folder_path: str | None = None,
    max_results: int = 20,
) -> dict[str, Any]:
    """Search for AE objects (jobs, workflows, etc.) by name, type, and/or folder.

    At least one of object_name, object_types, or folder_path is required.
    object_name supports the wildcards '*' and '?'. object_types are AE
    object type codes such as "JOBS", "JOBP", "SCRI". folder_path uses '\\'
    as the path separator, e.g. "\\PROJECT\\JOBS".
    """
    async with AutomicClient() as client:
        return await client.search_objects(
            object_name=object_name,
            object_types=object_types,
            folder_path=folder_path,
            max_results=max_results,
        )


@mcp.tool()
async def get_object(object_name: str) -> dict[str, Any]:
    """Get the full definition of a single AE object by its exact name."""
    async with AutomicClient() as client:
        return await client.get_object(object_name)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
