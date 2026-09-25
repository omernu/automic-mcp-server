"""Pure unit tests for stats.summarize_executions - plain dicts in, no HTTP
involved. Field names/shapes are grounded in the real OutExecution schema
in reference/automic-ae-rest-api.json.
"""

from automic_mcp.stats import summarize_executions


def _execution(status_text: str, runtime: int | None = None, status: int = 0) -> dict:
    execution = {"status_text": status_text, "status": status}
    if runtime is not None:
        execution["runtime"] = runtime
    return execution


def test_empty_list() -> None:
    result = summarize_executions([], truncated=False)
    assert result["sample_size"] == 0
    assert result["success_rate_percent"] is None
    assert result["runtime"] == {
        "count": 0,
        "avg_seconds": None,
        "min_seconds": None,
        "max_seconds": None,
    }


def test_counts_success_and_failure_by_status_code_name() -> None:
    executions = [
        _execution("ENDED_OK - Task ended normally.", runtime=60),
        _execution("ENDED_OK - Task ended normally.", runtime=100),
        _execution("ENDED_NOT_OK - Task ended abnormally.", runtime=10),
        _execution("ABEND - abended.", runtime=5),
        _execution("ACTIVE - still running."),  # no runtime yet - not finished
    ]

    result = summarize_executions(executions, truncated=False)

    assert result["sample_size"] == 5
    assert result["success_count"] == 2
    assert result["failure_count"] == 2
    assert result["other_count"] == 1
    assert result["status_counts"] == {
        "ENDED_OK": 2,
        "ENDED_NOT_OK": 1,
        "ABEND": 1,
        "ACTIVE": 1,
    }
    # success_rate is over *finished* executions only (2 success / 4 finished)
    assert result["success_rate_percent"] == 50.0


def test_runtime_stats_only_consider_executions_with_a_runtime() -> None:
    executions = [
        _execution("ENDED_OK - ok.", runtime=10),
        _execution("ENDED_OK - ok.", runtime=30),
        _execution("ACTIVE - running."),  # no runtime
    ]

    result = summarize_executions(executions, truncated=False)

    assert result["runtime"] == {
        "count": 2,
        "avg_seconds": 20.0,
        "min_seconds": 10,
        "max_seconds": 30,
    }


def test_missing_status_text_falls_back_to_numeric_status() -> None:
    executions = [{"status": 1234}]

    result = summarize_executions(executions, truncated=False)

    assert result["status_counts"] == {"STATUS_1234": 1}
    assert result["other_count"] == 1


def test_truncated_flag_is_passed_through() -> None:
    result = summarize_executions([_execution("ENDED_OK - ok.")], truncated=True)
    assert result["truncated"] is True
