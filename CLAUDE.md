# CLAUDE.md — mcp-gatekeeper

Read-only MCP server for ApiGatekeeper instances.

## Core invariant: READ-ONLY

This server exposes **only** the gatekeeper's `GET /api/admin/*` endpoints (clients, routes, permissions, rate limits). It must not contain any tool that issues POST, PUT, PATCH, or DELETE. If a task asks for "let the MCP create a client" or "add a permission via the MCP" — push back and refer the operator to the gatekeeper management scripts in `gatekeeper-backend/scripts/`. The whole point of this project is that an LLM granted access to it cannot mutate a gatekeeper.

## Architecture

- **HTTP client**: delegated to the [`api-gatekeeper-api`](https://github.com/jmazzahacks/api-gatekeeper-api-python) Python lib. Don't reach for `httpx` directly in this codebase — use `GatekeeperClient` from the lib. The lib is the single source of truth for the gatekeeper REST contract.
- **MCP framework**: [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (high-level decorator API).
- **Config**: env vars only, validated in `src/mcp_gatekeeper/config.py`. No config files.
- **Auth**: an Aegis bearer token in `GATEKEEPER_ADMIN_TOKEN`; the user supplying the token must already have console-admin role on the target gatekeeper.

## Python environment

Per workspace convention, the venv is created with `python -m venv .` at the project root (NOT `python -m venv bin` — that produces an extra nesting level). The activate script then lives at `bin/activate`.

```bash
python -m venv .                   # one-time setup
source bin/activate && python      # runs python
source bin/activate && pip ...     # installs packages
```

Never call `python3`. Never use `pip install -e ../api-gatekeeper-api-python` to satisfy the lib dependency — the project CLAUDE.md forbids local-path deps. The lib must be installed via its GitHub URL (see `pyproject.toml`).

## Adding a new read-only tool

The data contract flows: gatekeeper-backend → api-gatekeeper-models (dataclass) → api-gatekeeper-api (deserializes) → mcp-gatekeeper (wraps as tool). To add a tool that surfaces a new endpoint:

1. Confirm the corresponding endpoint exists in `gatekeeper-backend/src/blueprints/admin.py` and is a `GET`. Note the response shape — is it an existing model (Client/Route/ClientSummary/…) or something new?
2. If the response is a new shape: add a dataclass to [`api-gatekeeper-models`](https://github.com/jmazzahacks/api-gatekeeper-models) with `to_dict()` + `from_dict()`. Add a round-trip test. Bump version, commit, push, tag.
3. Add a method to `GatekeeperClient` in [`api-gatekeeper-api-python`](https://github.com/jmazzahacks/api-gatekeeper-api-python). The method should call `_get_raw()` and run `Model.from_dict(item)` over each entry. Add a test. Bump version, commit, push, tag.
4. Add an `@mcp.tool()` wrapper in `src/mcp_gatekeeper/server.py` with the typed return (e.g. `-> list[ClientSummary]`). FastMCP will auto-generate a precise JSON Schema from the dataclass — the LLM sees real field names and enum values.
5. Docstring should describe specific field names (LLMs read these to decide when to call the tool). Don't be vague — say `client_id` not "an identifier".
6. No tests for thin wrappers — they're 1-line delegators. Tools with branching (like `show_client`) get tests in `tests/test_server.py`.

## Testing

```bash
source bin/activate && pytest
```

`tests/test_config.py` covers config parsing. `tests/test_server.py` covers tool wrappers with non-trivial logic. HTTP behavior is tested upstream in `api-gatekeeper-api-python`.

## What this server is NOT

- It is not the gatekeeper itself.
- It is not an admin console — use `gatekeeper-frontend` for that.
- It is not a CLI — use the scripts under `gatekeeper-backend/scripts/`.
- It is not a write tool. (Saying this twice intentionally.)
