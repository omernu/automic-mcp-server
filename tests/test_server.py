"""Stage 2 tests: the tools are registered correctly on the FastMCP server,
and an end-to-end call through FastMCP -> AutomicClient -> httpx works
against a mocked Automic API (no real network call).
"""

import httpx
import pytest
import respx

from automic_mcp.config import get_settings
from automic_mcp.server import mcp


async def test_expected_tools_are_registered() -> None:
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "ping_automic",
        "search_objects",
        "get_object",
        "list_executions",
        "get_job_statistics",
    }


async def test_get_object_tool_schema_requires_object_name() -> None:
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "get_object")
    assert tool.inputSchema["required"] == ["object_name"]


@pytest.fixture(autouse=True)
def _fake_automic_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTOMIC_BASE_URL", "https://automic.example.com:8088/ae/api/v1")
    monkeypatch.setenv("AUTOMIC_CLIENT_ID", "100")
    monkeypatch.setenv("AUTOMIC_USERNAME", "testuser")
    monkeypatch.setenv("AUTOMIC_PASSWORD", "testpass")
    # Explicit, even though it's the field default: get_settings() still
    # falls back to the developer's real local .env for any var not set
    # here, which made this fixture's behavior depend on that file's
    # contents (see AutomicSettings(_env_file=None, ...) in
    # test_automic_client.py for the same issue on that other path).
    monkeypatch.setenv("AUTOMIC_VERIFY_SSL", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_search_objects_end_to_end_through_mcp_call_tool() -> None:
    fixture = {"data": [{"name": "DAILY_BACKUP", "type": "JOBS"}], "total": 1, "hasmore": False}

    with respx.mock(base_url="https://automic.example.com:8088/ae/api/v1") as mock:
        mock.post("/100/search").mock(return_value=httpx.Response(200, json=fixture))
        result = await mcp.call_tool("search_objects", {"object_name": "DAILY*"})

    # search_objects returns `dict[str, Any]` (a *parameterized* dict type,
    # unlike stage 1's bare `dict`) - FastMCP treats that as structured-output
    # capable, so call_tool() here returns a (content_blocks, structured_dict)
    # tuple instead of just a content_blocks list.
    content_blocks, structured = result
    assert structured == fixture
    assert content_blocks[0].text  # human-readable text form is still present


async def test_get_job_statistics_end_to_end_through_mcp_call_tool() -> None:
    fixture = {
        "data": [
            {"run_id": 1, "status_text": "ENDED_OK - ok.", "runtime": 30},
            {"run_id": 2, "status_text": "ENDED_NOT_OK - failed.", "runtime": 5},
        ],
        "total": 2,
        "hasmore": False,
    }

    with respx.mock(base_url="https://automic.example.com:8088/ae/api/v1") as mock:
        mock.get("/100/executions").mock(return_value=httpx.Response(200, json=fixture))
        result = await mcp.call_tool("get_job_statistics", {"object_name": "DAILY*"})

    _, structured = result
    assert structured["sample_size"] == 2
    assert structured["success_count"] == 1
    assert structured["failure_count"] == 1
    assert structured["truncated"] is False
