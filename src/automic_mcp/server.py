"""FastMCP server with read-only tools backed by the real Automic AE REST
API: object queries (stage 2) and execution statistics (stage 3).

The stage-1 mock tool has been removed now that we have real read tools -
keeping a fake tool alongside real ones risked confusing whichever client
(human or LLM) picks a tool to call.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from automic_mcp.automic_client import AutomicClient
from automic_mcp.stats import ExecutionStatistics, summarize_executions

mcp = FastMCP(
    "automic-mcp-server",
    instructions=(
        "MCP server for the Broadcom Automic Automation Engine. Read-only "
        "tools for querying AE objects (jobs, workflows, etc.) and execution "
        "statistics. No object is ever created, modified, deleted, or "
        "executed by these tools."
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


@mcp.tool()
async def list_executions(
    object_name: str | None = None,
    object_types: list[str] | None = None,
    time_frame_from: str | None = None,
    time_frame_to: str | None = None,
    max_results: int = 50,
) -> dict[str, Any]:
    """List AE job/workflow executions (runs), most recent first.

    object_name supports wildcards ('*', '?'). object_types are AE object
    type codes such as "JOBS", "JOBP". time_frame_from/time_frame_to are
    ISO 8601 UTC timestamps, e.g. "2026-09-01T00:00:00Z", filtering by
    activation time.
    """
    async with AutomicClient() as client:
        return await client.list_executions(
            object_name=object_name,
            object_types=object_types,
            time_frame_from=time_frame_from,
            time_frame_to=time_frame_to,
            max_results=max_results,
        )


@mcp.tool()
async def get_job_statistics(
    object_name: str | None = None,
    object_types: list[str] | None = None,
    time_frame_from: str | None = None,
    time_frame_to: str | None = None,
    max_executions: int = 500,
) -> ExecutionStatistics:
    """Compute summary statistics over AE job/workflow executions.

    Returns counts by status, a success rate (ENDED_OK vs ENDED_NOT_OK /
    ABEND* among finished executions only - still-running/waiting/cancelled
    runs are excluded from that rate), and runtime (seconds) min/avg/max.

    At least one filter (object_name, object_types, time_frame_from, or
    time_frame_to) should normally be given - an unfiltered call summarizes
    the most recent max_executions runs across the whole client.

    max_executions caps how many execution records are fetched and
    aggregated (a safety limit, not the true total if more runs match); the
    result's "truncated" field tells you whether the sample covers
    everything that matched or was capped.
    """
    executions = []
    async with AutomicClient() as client:
        async for execution in client.iter_executions(
            object_name=object_name,
            object_types=object_types,
            time_frame_from=time_frame_from,
            time_frame_to=time_frame_to,
            max_total=max_executions,
        ):
            executions.append(execution)

    truncated = len(executions) >= max_executions
    return summarize_executions(executions, truncated=truncated)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
