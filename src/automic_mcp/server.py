"""FastMCP server with tools backed by the real Automic AE REST API:
object queries (stage 2), execution statistics (stage 3), and guarded
execution (stage 4).

The stage-1 mock tool has been removed now that we have real read tools -
keeping a fake tool alongside real ones risked confusing whichever client
(human or LLM) picks a tool to call.
"""

import time
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from typing_extensions import TypedDict

from automic_mcp import audit
from automic_mcp.automic_client import AutomicClient
from automic_mcp.config import get_settings
from automic_mcp.guardrails import Cooldown, TokenStore, matches_allowlist
from automic_mcp.stats import ExecutionStatistics, summarize_executions

mcp = FastMCP(
    "automic-mcp-server",
    instructions=(
        "MCP server for the Broadcom Automic Automation Engine. Read-only "
        "tools for querying AE objects (jobs, workflows, etc.) and execution "
        "statistics, plus a guarded two-step flow (preview_execution then "
        "execute_object) to run a job/workflow. Nothing is ever created, "
        "modified, or deleted. Execution is off by default and restricted "
        "to an explicit allowlist - see preview_execution."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# Module-level, in-process state for the execution guardrails. Resets on
# every server restart - intentional: a pending preview or an in-progress
# cooldown shouldn't outlive the process.
_token_store = TokenStore()
_cooldown = Cooldown()


@mcp.tool(annotations=READ_ONLY)
async def ping_automic() -> dict[str, str]:
    """Check whether the Automic AE REST API is reachable and responding."""
    async with AutomicClient() as client:
        await client.ping()
    return {"status": "ok"}


@mcp.tool(annotations=READ_ONLY)
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


@mcp.tool(annotations=READ_ONLY)
async def get_object(object_name: str) -> dict[str, Any]:
    """Get the full definition of a single AE object by its exact name."""
    async with AutomicClient() as client:
        return await client.get_object(object_name)


@mcp.tool(annotations=READ_ONLY)
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


@mcp.tool(annotations=READ_ONLY)
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


class ExecutionPreview(TypedDict):
    object_name: str
    object_type: str | None
    folder_path: str | None
    inputs: dict[str, Any] | None
    confirmation_token: str
    expires_in_seconds: int


class ExecutionResult(TypedDict):
    object_name: str
    run_id: int
    status: str


@mcp.tool(annotations=READ_ONLY)
async def preview_execution(
    object_name: str, inputs: dict[str, Any] | None = None
) -> ExecutionPreview:
    """Step 1 of 2 to run an AE job/workflow. Does not execute anything.

    Checks that execution is enabled and object_name is on the allowlist,
    confirms the object exists, and returns a one-time confirmation_token
    (valid briefly) that execute_object requires. This tool never runs
    anything by itself - it only prepares and authorizes a specific,
    single execution.
    """
    settings = get_settings()
    now = time.time()
    log = {"action": "preview_execution", "object_name": object_name}

    if not settings.allow_execute:
        audit.log_event(
            settings.audit_log_path,
            {**log, "decision": "denied", "reason": "execution disabled (AUTOMIC_ALLOW_EXECUTE=false)"},
        )
        raise PermissionError("Execution is disabled (AUTOMIC_ALLOW_EXECUTE=false).")

    if not matches_allowlist(object_name, settings.execute_allowlist_patterns):
        audit.log_event(
            settings.audit_log_path,
            {**log, "decision": "denied", "reason": "not in AUTOMIC_EXECUTE_ALLOWLIST"},
        )
        raise PermissionError(f"{object_name!r} is not in AUTOMIC_EXECUTE_ALLOWLIST.")

    async with AutomicClient() as client:
        search_result = await client.search_objects(object_name=object_name, max_results=1)

    matches = search_result.get("data", [])
    if not matches:
        audit.log_event(
            settings.audit_log_path,
            {**log, "decision": "denied", "reason": "object not found via search"},
        )
        raise ValueError(f"No object named {object_name!r} was found.")

    found = matches[0]
    token = _token_store.create(
        object_name, inputs, ttl_seconds=settings.execute_confirmation_ttl_seconds, now=now
    )

    audit.log_event(settings.audit_log_path, {**log, "decision": "preview_issued", "token": token})

    return {
        "object_name": object_name,
        "object_type": found.get("type"),
        "folder_path": found.get("folder_path"),
        "inputs": inputs,
        "confirmation_token": token,
        "expires_in_seconds": settings.execute_confirmation_ttl_seconds,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
    )
)
async def execute_object(confirmation_token: str) -> ExecutionResult:
    """Step 2 of 2: actually run the job/workflow previewed by
    preview_execution, using its confirmation_token. This is the only tool
    in this server that changes anything in Automic.

    Refuses to run without a valid, unexpired token from a matching
    preview_execution call. The token is single-use - request a new preview
    for every execution, even a repeat of the same object.
    """
    settings = get_settings()
    now = time.time()
    log: dict[str, Any] = {"action": "execute_object"}

    pending = _token_store.consume(confirmation_token, now=now)
    if pending is None:
        audit.log_event(
            settings.audit_log_path,
            {**log, "decision": "denied", "reason": "invalid or expired confirmation_token"},
        )
        raise PermissionError(
            "Invalid or expired confirmation_token - call preview_execution again."
        )

    log["object_name"] = pending.object_name

    # Re-checked here, not just at preview time, in case config or the
    # allowlist changed in between.
    if not settings.allow_execute:
        audit.log_event(
            settings.audit_log_path,
            {**log, "decision": "denied", "reason": "execution disabled (AUTOMIC_ALLOW_EXECUTE=false)"},
        )
        raise PermissionError("Execution is disabled (AUTOMIC_ALLOW_EXECUTE=false).")

    if not matches_allowlist(pending.object_name, settings.execute_allowlist_patterns):
        audit.log_event(
            settings.audit_log_path,
            {**log, "decision": "denied", "reason": "no longer in AUTOMIC_EXECUTE_ALLOWLIST"},
        )
        raise PermissionError(f"{pending.object_name!r} is no longer in AUTOMIC_EXECUTE_ALLOWLIST.")

    if not _cooldown.ready(now, settings.execute_cooldown_seconds):
        audit.log_event(settings.audit_log_path, {**log, "decision": "denied", "reason": "cooldown"})
        raise PermissionError(
            f"Execution cooldown active - wait {settings.execute_cooldown_seconds}s between runs."
        )

    async with AutomicClient() as client:
        result = await client.execute_object(pending.object_name, pending.inputs)

    _cooldown.record_success(now)
    audit.log_event(
        settings.audit_log_path, {**log, "decision": "executed", "run_id": result.get("run_id")}
    )

    return {"object_name": pending.object_name, "run_id": result["run_id"], "status": "submitted"}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
