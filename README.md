# automic-mcp-server

An MCP (Model Context Protocol) server for the Broadcom Automic Automation
Engine (AE) REST API. It exposes AE objects, job/workflow execution
statistics, and a guarded flow for actually running a job, as MCP tools -
usable from Claude Desktop, Claude Code, or any other MCP client.

This is a learning project, built incrementally in 4 stages. See
[LEARNING.md](LEARNING.md) for the full history of decisions and issues hit
along the way.

## Requirements

- Python 3.10+ (the project was built and tested on 3.11)
- Node.js + `npx` (only needed for the MCP Inspector - see "Manual testing"
  below)
- Network access to your Automic AE REST API endpoint (check with your
  Automic admin if you're not sure it's reachable from your machine)
- An AE user/login with REST API access

## Setup

```bash
git clone <this-repo-url>
cd automic-mcp-server

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

`.[dev]` also installs `pytest`, `respx`, and `uv` (the last one is only
used by the MCP Inspector, see below).

## Configuration (`.env`)

```bash
cp .env.example .env
```

Then edit `.env` with real values. **Never commit `.env`** - it's already
gitignored.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `AUTOMIC_BASE_URL` | yes | - | `http[s]://{host}:{port}/ae/api/v1` - ask your Automic admin for host/port. Must end in `/v1`. |
| `AUTOMIC_CLIENT_ID` | yes | - | AE client (tenant) number. |
| `AUTOMIC_USERNAME` | yes | - | AE login used for Basic Auth. |
| `AUTOMIC_PASSWORD` | yes | - | AE password. |
| `AUTOMIC_DEPARTMENT` | no | unset | AE department, if your login needs one. |
| `AUTOMIC_VERIFY_SSL` | no | `true` | Set to `false` **only** if your AE server uses a self-signed certificate (equivalent to `curl -k`). Never disable for a server reachable over the public internet. |
| `AUTOMIC_ALLOW_EXECUTE` | no | `false` | Master switch for the `execute_object` tool. Must be explicitly `true` to allow running anything. |
| `AUTOMIC_EXECUTE_ALLOWLIST` | no | empty | Comma-separated object names/wildcard patterns (`*`, `?`) allowed to run via `execute_object`, e.g. `DAILY_BACKUP,TEST.JOBS.*`. Empty means nothing is allowed, even with `AUTOMIC_ALLOW_EXECUTE=true`. Be as specific as possible - avoid a bare `*`. |
| `AUTOMIC_EXECUTE_CONFIRMATION_TTL_SECONDS` | no | `120` | How long a `preview_execution` confirmation token stays valid. |
| `AUTOMIC_EXECUTE_COOLDOWN_SECONDS` | no | `5` | Minimum time between successful executions. |
| `AUTOMIC_AUDIT_LOG_PATH` | no | `logs/executions.jsonl` | Local, gitignored log of every execution attempt (allowed or denied). |

**If your AE server uses a self-signed certificate**, you'll see
`SSLError: CERTIFICATE_VERIFY_FAILED` the first time you call any tool.
Set `AUTOMIC_VERIFY_SSL=false` in `.env` and restart the server.

## Running the server

### Manual testing (MCP Inspector)

The quickest way to try the tools by hand, without wiring up a full MCP
client:

```bash
source .venv/bin/activate
mcp dev src/automic_mcp/server.py
```

This opens a browser UI. Click **Connect**, then go to the **Tools** tab to
list, inspect, and call every tool. The first run may take a few seconds
(it builds an isolated environment via `uv`).

### From an MCP client (Claude Desktop / Claude Code)

Point the client at the venv's Python and the server module, e.g. in
Claude Desktop's config:

```json
{
  "mcpServers": {
    "automic": {
      "command": "/absolute/path/to/automic-mcp-server/.venv/bin/automic-mcp-server"
    }
  }
}
```

(Use the venv's `automic-mcp-server` executable directly - it already has
all dependencies installed, no `uv`/`npx` needed for this path.)

## Available tools

**Read-only** (safe to call anytime, never change anything in Automic):

| Tool | Purpose |
|---|---|
| `ping_automic` | Check connectivity to the Automic REST API. |
| `search_objects(object_name?, object_types?, folder_path?, max_results?)` | Search AE objects (jobs, workflows, ...) by name (wildcards `*`/`?` supported), type, and/or folder. |
| `get_object(object_name)` | Get the full definition of one AE object by exact name. |
| `list_executions(object_name?, object_types?, time_frame_from?, time_frame_to?, max_results?)` | List job/workflow runs, most recent first. |
| `get_job_statistics(object_name?, object_types?, time_frame_from?, time_frame_to?, max_executions?)` | Aggregate stats over runs: status counts, success rate, runtime min/avg/max. |

**Execution** (changes real state in Automic - disabled by default, see
Configuration above):

| Tool | Purpose |
|---|---|
| `preview_execution(object_name, inputs?)` | Step 1/2. Validates the request (allowlist, object exists) and returns a one-time `confirmation_token`. Runs nothing. |
| `execute_object(confirmation_token)` | Step 2/2. Actually runs the job/workflow previewed above. Requires a valid, unexpired token from a matching `preview_execution` call. |

To run something: call `preview_execution` first, copy the
`confirmation_token` from its result, then call `execute_object` with that
token before it expires (`AUTOMIC_EXECUTE_CONFIRMATION_TTL_SECONDS`,
120s default). The object must match `AUTOMIC_EXECUTE_ALLOWLIST` or the
preview is refused.

## Running tests

```bash
source .venv/bin/activate
python -m pytest -v
```

Tests never call the real Automic API - they use `respx` to mock HTTP
responses, grounded in the real OpenAPI spec examples where relevant. No
`.env` values are required to run the test suite.

## Project structure

```
src/automic_mcp/
├── server.py          # FastMCP server: tool definitions
├── automic_client.py  # Thin async HTTP client for the AE REST API
├── config.py           # .env-backed settings (pydantic-settings)
├── stats.py             # Pure execution-statistics aggregation
├── guardrails.py       # Pure execution guardrails (allowlist, tokens, cooldown)
└── audit.py             # Local execution audit log
tests/                  # pytest suite (respx-mocked, no real network calls)
```

## Safety notes on `execute_object`

- Disabled by default (`AUTOMIC_ALLOW_EXECUTE=false`) - must be explicitly
  turned on.
- Only objects matching `AUTOMIC_EXECUTE_ALLOWLIST` can be run. An empty
  allowlist allows nothing.
- Only immediate execution is supported (no scheduling a future or
  recurring run).
- Every attempt - allowed or denied - is appended to
  `AUTOMIC_AUDIT_LOG_PATH` for accountability.
- Consider using an AE login with the minimum execute permissions it
  actually needs (defense in depth - this server's guardrails are a second
  layer, not a replacement for AE's own authorization).
