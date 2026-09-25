"""Stage 4 end-to-end tests: preview_execution -> execute_object through
mcp.call_tool(), against a mocked Automic API. Base env (AUTOMIC_ALLOW_EXECUTE
and AUTOMIC_EXECUTE_ALLOWLIST both empty/false) comes from conftest.py's
_fake_automic_env - each test here opts in to what it needs.

Note: mcp.call_tool() (the in-process FastMCP method used here) *raises*
mcp.server.fastmcp.exceptions.ToolError when a tool raises internally. This
differs from the full stdio/JSON-RPC protocol layer, which instead returns a
normal response with isError: true (see LEARNING.md, stage 2, for where we
first observed that isError behavior) - call_tool() is one level below that.
"""

import httpx
import pytest
import respx
from mcp.server.fastmcp.exceptions import ToolError

from automic_mcp.server import mcp

BASE_URL = "https://automic.example.com:8088/ae/api/v1"


def _mock_search_finds(mock: respx.MockRouter, object_name: str) -> None:
    mock.post("/100/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"name": object_name, "type": "JOBS", "folder_path": "\\PROJECT"}],
                "total": 1,
                "hasmore": False,
            },
        )
    )


async def test_preview_denied_when_execution_disabled() -> None:
    # AUTOMIC_ALLOW_EXECUTE=false comes from the base fixture - not overridden here.
    with pytest.raises(ToolError, match="disabled"):
        await mcp.call_tool("preview_execution", {"object_name": "DAILY_BACKUP"})


async def test_preview_denied_when_not_in_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from automic_mcp.config import get_settings

    monkeypatch.setenv("AUTOMIC_ALLOW_EXECUTE", "true")
    monkeypatch.setenv("AUTOMIC_EXECUTE_ALLOWLIST", "SOME.OTHER.JOB")
    get_settings.cache_clear()

    with pytest.raises(ToolError, match="not in AUTOMIC_EXECUTE_ALLOWLIST"):
        await mcp.call_tool("preview_execution", {"object_name": "DAILY_BACKUP"})


async def test_preview_denied_when_object_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from automic_mcp.config import get_settings

    monkeypatch.setenv("AUTOMIC_ALLOW_EXECUTE", "true")
    monkeypatch.setenv("AUTOMIC_EXECUTE_ALLOWLIST", "DAILY_BACKUP")
    get_settings.cache_clear()

    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/100/search").mock(
            return_value=httpx.Response(200, json={"data": [], "total": 0, "hasmore": False})
        )
        with pytest.raises(ToolError, match="No object named"):
            await mcp.call_tool("preview_execution", {"object_name": "DAILY_BACKUP"})


async def test_preview_succeeds_and_returns_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from automic_mcp.config import get_settings

    monkeypatch.setenv("AUTOMIC_ALLOW_EXECUTE", "true")
    monkeypatch.setenv("AUTOMIC_EXECUTE_ALLOWLIST", "DAILY_BACKUP")
    get_settings.cache_clear()

    with respx.mock(base_url=BASE_URL) as mock:
        _mock_search_finds(mock, "DAILY_BACKUP")
        result = await mcp.call_tool("preview_execution", {"object_name": "DAILY_BACKUP"})

    _, structured = result
    assert structured["object_name"] == "DAILY_BACKUP"
    assert structured["object_type"] == "JOBS"
    assert structured["confirmation_token"]
    assert structured["expires_in_seconds"] == 120


async def test_execute_denied_with_unknown_token() -> None:
    with pytest.raises(ToolError, match="Invalid or expired"):
        await mcp.call_tool("execute_object", {"confirmation_token": "never-issued"})


async def test_full_preview_then_execute_flow_submits_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from automic_mcp.config import get_settings

    monkeypatch.setenv("AUTOMIC_ALLOW_EXECUTE", "true")
    monkeypatch.setenv("AUTOMIC_EXECUTE_ALLOWLIST", "DAILY_BACKUP")
    get_settings.cache_clear()

    with respx.mock(base_url=BASE_URL) as mock:
        _mock_search_finds(mock, "DAILY_BACKUP")
        preview_result = await mcp.call_tool("preview_execution", {"object_name": "DAILY_BACKUP"})
        _, preview = preview_result
        token = preview["confirmation_token"]

        mock.post("/100/executions").mock(
            return_value=httpx.Response(200, json={"run_id": 42})
        )
        execute_result = await mcp.call_tool("execute_object", {"confirmation_token": token})

    _, executed = execute_result
    assert executed == {"object_name": "DAILY_BACKUP", "run_id": 42, "status": "submitted"}


async def test_execute_token_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    from automic_mcp.config import get_settings

    monkeypatch.setenv("AUTOMIC_ALLOW_EXECUTE", "true")
    monkeypatch.setenv("AUTOMIC_EXECUTE_ALLOWLIST", "DAILY_BACKUP")
    get_settings.cache_clear()

    with respx.mock(base_url=BASE_URL) as mock:
        _mock_search_finds(mock, "DAILY_BACKUP")
        _, preview = (await mcp.call_tool("preview_execution", {"object_name": "DAILY_BACKUP"}))
        token = preview["confirmation_token"]

        mock.post("/100/executions").mock(return_value=httpx.Response(200, json={"run_id": 1}))
        await mcp.call_tool("execute_object", {"confirmation_token": token})

        with pytest.raises(ToolError, match="Invalid or expired"):
            await mcp.call_tool("execute_object", {"confirmation_token": token})


async def test_execute_denied_by_cooldown_after_a_successful_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from automic_mcp.config import get_settings

    monkeypatch.setenv("AUTOMIC_ALLOW_EXECUTE", "true")
    monkeypatch.setenv("AUTOMIC_EXECUTE_ALLOWLIST", "DAILY_BACKUP")
    monkeypatch.setenv("AUTOMIC_EXECUTE_COOLDOWN_SECONDS", "3600")  # effectively "don't allow a 2nd run"
    get_settings.cache_clear()

    with respx.mock(base_url=BASE_URL) as mock:
        _mock_search_finds(mock, "DAILY_BACKUP")
        mock.post("/100/executions").mock(return_value=httpx.Response(200, json={"run_id": 1}))

        _, first_preview = await mcp.call_tool("preview_execution", {"object_name": "DAILY_BACKUP"})
        await mcp.call_tool("execute_object", {"confirmation_token": first_preview["confirmation_token"]})

        _, second_preview = await mcp.call_tool("preview_execution", {"object_name": "DAILY_BACKUP"})
        with pytest.raises(ToolError, match="cooldown"):
            await mcp.call_tool(
                "execute_object", {"confirmation_token": second_preview["confirmation_token"]}
            )
