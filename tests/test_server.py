"""Stage 1 tests: verify the mock tool is registered and callable through
FastMCP's own in-process API (no stdio subprocess, no real transport) -
this is enough to exercise the real MCP request/response path.
"""

import json

from automic_mcp.server import mcp


async def test_get_fake_job_status_is_registered_with_correct_schema():
    tools = await mcp.list_tools()
    names = [t.name for t in tools]
    assert "get_fake_job_status" in names

    tool = next(t for t in tools if t.name == "get_fake_job_status")
    assert tool.inputSchema["required"] == ["job_name"]
    assert tool.inputSchema["properties"]["job_name"]["type"] == "string"


async def test_get_fake_job_status_call_returns_expected_payload():
    result = await mcp.call_tool("get_fake_job_status", {"job_name": "DAILY_BACKUP"})

    # FastMCP wraps a plain dict return as a single text content block
    # holding the JSON-serialized payload (no output schema was declared).
    assert len(result) == 1
    payload = json.loads(result[0].text)

    assert payload["job_name"] == "DAILY_BACKUP"
    assert payload["status"] == "SUCCESSFUL"
