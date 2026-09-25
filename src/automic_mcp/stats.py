"""Pure aggregation logic for execution statistics.

Kept separate from automic_client.py (HTTP) and server.py (MCP tool
wiring) so it can be unit-tested with plain dicts - no HTTP mocking needed.
"""

from typing import Any

from typing_extensions import TypedDict  # pydantic needs this over typing.TypedDict on Python < 3.12


class RuntimeStats(TypedDict):
    count: int
    avg_seconds: float | None
    min_seconds: int | None
    max_seconds: int | None


class ExecutionStatistics(TypedDict):
    sample_size: int
    truncated: bool
    status_counts: dict[str, int]
    success_count: int
    failure_count: int
    other_count: int
    success_rate_percent: float | None
    runtime: RuntimeStats


def _status_code_name(execution: dict[str, Any]) -> str:
    """Extract the AE status code name from status_text, e.g. "ENDED_OK -
    Task ended normally." -> "ENDED_OK". Falls back to the raw numeric
    status if status_text is missing/unrecognized.

    This parsing is based on the example format in the API docs, not a
    documented contract - worth re-verifying against real execution data.
    """
    status_text = execution.get("status_text")
    if isinstance(status_text, str) and status_text.strip():
        return status_text.split(" - ", 1)[0].strip()
    return f"STATUS_{execution.get('status', 'UNKNOWN')}"


def summarize_executions(
    executions: list[dict[str, Any]], *, truncated: bool
) -> ExecutionStatistics:
    """Aggregate a list of raw OutExecution dicts into summary statistics.

    `truncated` should be True when the caller stopped paging before
    exhausting all matching executions (e.g. hit a safety cap), so callers
    of this function know the counts are a sample, not the full population.
    """
    status_counts: dict[str, int] = {}
    success_count = 0
    failure_count = 0
    other_count = 0
    runtimes: list[int] = []

    for execution in executions:
        code_name = _status_code_name(execution)
        status_counts[code_name] = status_counts.get(code_name, 0) + 1

        if code_name == "ENDED_OK":
            success_count += 1
        elif code_name.startswith("ENDED_NOT_OK") or code_name.startswith("ABEND"):
            failure_count += 1
        else:
            other_count += 1

        runtime = execution.get("runtime")
        if isinstance(runtime, int):
            runtimes.append(runtime)

    finished_count = success_count + failure_count
    success_rate_percent = (
        round(100 * success_count / finished_count, 1) if finished_count else None
    )

    runtime_stats: RuntimeStats = {
        "count": len(runtimes),
        "avg_seconds": round(sum(runtimes) / len(runtimes), 1) if runtimes else None,
        "min_seconds": min(runtimes) if runtimes else None,
        "max_seconds": max(runtimes) if runtimes else None,
    }

    return {
        "sample_size": len(executions),
        "truncated": truncated,
        "status_counts": status_counts,
        "success_count": success_count,
        "failure_count": failure_count,
        "other_count": other_count,
        "success_rate_percent": success_rate_percent,
        "runtime": runtime_stats,
    }
