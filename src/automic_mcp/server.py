"""Stage 1: minimal FastMCP server with a single mock tool.

No connection to Automic yet — the goal here is to learn the shape of an
MCP tool (schema generation from type hints, docstring-as-description,
request/response) before adding any real integration.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "automic-mcp-server",
    instructions=(
        "Prototype MCP server for the Broadcom Automic Automation Engine. "
        "This stage only exposes a mock tool; no real Automic calls happen yet."
    ),
)


@mcp.tool()
def get_fake_job_status(job_name: str) -> dict:
    """Return a made-up status for the given job name.

    This mimics the shape a real "job status" tool will have once we wire up
    the Automic REST API in a later stage: it takes a job name and returns
    structured info about its last run. For now the data is hardcoded.
    """
    return {
        "job_name": job_name,
        "status": "SUCCESSFUL",
        "last_run": "2026-09-24T21:00:00Z",
        "run_id": "FAKE-000001",
        "note": "Mock data - this stage does not talk to Automic yet.",
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
