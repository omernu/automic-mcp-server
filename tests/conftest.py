"""Shared fixtures for tests that go through automic_mcp.server (FastMCP
tools), used by both test_server.py and test_execute_guardrails.py.
"""

import pytest

from automic_mcp.config import get_settings
from automic_mcp.guardrails import Cooldown, TokenStore


@pytest.fixture(autouse=True)
def _fake_automic_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("AUTOMIC_BASE_URL", "https://automic.example.com:8088/ae/api/v1")
    monkeypatch.setenv("AUTOMIC_CLIENT_ID", "100")
    monkeypatch.setenv("AUTOMIC_USERNAME", "testuser")
    monkeypatch.setenv("AUTOMIC_PASSWORD", "testpass")
    # Explicit, even though these are the field defaults: get_settings()
    # still falls back to the developer's real local .env for any var not
    # set here, which would make these tests depend on that file's
    # contents (see AutomicSettings(_env_file=None, ...) in
    # test_automic_client.py for the same issue on a different code path).
    monkeypatch.setenv("AUTOMIC_VERIFY_SSL", "true")
    monkeypatch.setenv("AUTOMIC_ALLOW_EXECUTE", "false")
    monkeypatch.setenv("AUTOMIC_EXECUTE_ALLOWLIST", "")
    # Found by running the real server and then running the test suite:
    # without this, AUTOMIC_AUDIT_LOG_PATH defaulted to logs/executions.jsonl
    # relative to cwd - the developer's *real* audit log - and every test
    # run appended a batch of fake preview/execute events into it, making
    # the real log useless for debugging an actual execution attempt.
    monkeypatch.setenv("AUTOMIC_AUDIT_LOG_PATH", str(tmp_path / "executions.jsonl"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_execution_guardrail_state(monkeypatch: pytest.MonkeyPatch):
    """automic_mcp.server keeps its confirmation-token store and cooldown
    tracker as module-level state, so it survives across tool calls within
    one running server process (by design). Tests must not share that
    state across test functions, so each test gets fresh instances."""
    import automic_mcp.server as server_module

    monkeypatch.setattr(server_module, "_token_store", TokenStore())
    monkeypatch.setattr(server_module, "_cooldown", Cooldown())
