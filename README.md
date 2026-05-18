# mcp-gatekeeper

A read-only [MCP](https://modelcontextprotocol.io) server for [ApiGatekeeper](https://github.com/jmazzahacks/api-gatekeeper) instances.

Surfaces gatekeeper's `/api/admin` GET endpoints as MCP tools so an LLM client can enumerate clients, routes, permissions, and rate limits without any ability to mutate the gatekeeper. Write operations are explicitly out of scope — if you need to provision clients or routes, use the gatekeeper management scripts directly.

## Tools

| Tool | Purpose |
|---|---|
| `list_clients` | List every client (API credential) |
| `list_routes` | List every route the gatekeeper enforces |
| `list_permissions` | List every client→route permission grant |
| `list_rate_limits` | List per-client rate-limit configurations |
| `show_client` | Return one client by id (client-side filter over `list_clients`) |

## Configuration

| Env var | Required | Default (image) | Notes |
|---|---|---|---|
| `GATEKEEPER_BASE_URL` | yes | — | e.g. `https://gatekeeper.example.com` |
| `GATEKEEPER_ADMIN_TOKEN` | yes | — | Aegis bearer token for a console-admin user |
| `GATEKEEPER_REQUEST_TIMEOUT_SECONDS` | no | `10` | HTTP request timeout in seconds |
| `MCP_TRANSPORT` | no | `streamable-http` *(image)* / `stdio` *(direct)* | one of `stdio`, `streamable-http`, `sse`. The Docker image overrides the source default to `streamable-http` |
| `MCP_HOST` | no | `127.0.0.1` | Bind address for streamable-http/sse. Image default is **safe-by-default** — compose example overrides to `0.0.0.0` to make the listener reachable through the port mapping. Ignored in stdio mode. |
| `MCP_PORT` | no | `7872` | Port for streamable-http/sse. |
| `FASTMCP_HOST` | no | `127.0.0.1` | FastMCP-specific alias. **Must be set** alongside `MCP_HOST` because FastMCP's pydantic-settings defaults override generic `MCP_HOST` otherwise. |
| `FASTMCP_PORT` | no | `7872` | FastMCP-specific alias — same precedence quirk as `FASTMCP_HOST`. |
| `DEBUG_LOCAL` | no | `true` | `true` = console logs. `false` = ship structured JSON to Loki under `application=mcp-gatekeeper`. Falls back to stdout if Loki is unreachable. |
| `LOG_LEVEL` | no | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LOKI_ENDPOINT` | only if `DEBUG_LOCAL=false` | — | e.g. `https://loki.example.com/loki/api/v1/push` |
| `LOKI_USER` | only if `DEBUG_LOCAL=false` | — | HTTP Basic auth user. |
| `LOKI_PASSWORD` | only if `DEBUG_LOCAL=false` | — | HTTP Basic auth password. |
| `LOKI_CA_BUNDLE_PATH` | only if `DEBUG_LOCAL=false` and Loki uses a private CA | — | Path inside the container, e.g. `/app/certs/loki-ca.pem`. Set to `false` to skip TLS verification (not recommended). |

## Run locally (stdio, for use with Claude Code / similar)

```bash
python -m venv .
source bin/activate
pip install -e .
GATEKEEPER_BASE_URL=https://gk.example.com \
GATEKEEPER_ADMIN_TOKEN=<aegis-bearer-token> \
  mcp-gatekeeper
```

Then register with your MCP client (e.g. add to `.mcp.json` as a `stdio` server pointing at the `mcp-gatekeeper` entry point).

## Run remote (streamable-http behind nginx)

1. `cp docker-compose.example.yml docker-compose.yml` and adjust if needed.
2. `cp env.example .env` and fill in `GATEKEEPER_BASE_URL` + `GATEKEEPER_ADMIN_TOKEN`. **Do not** export these on the command line — `.env` is gitignored, shell history is not.
3. `cp nginx/mcp-gatekeeper.conf.example` to your nginx sites-available, swap the domain + cert paths, and create the bearer-token include at `/etc/nginx/snippets/mcp-gatekeeper-tokens.map` per the comments in that file.
4. `docker compose up -d` then `nginx -t && nginx -s reload`.

## Development

```bash
source bin/activate
pip install -e ".[dev]"
pytest
```

## License

O'Saasy — see [LICENSE](LICENSE) and [osaasy.dev](https://osaasy.dev/).

## Author

Jason Byteforge ([@jmazzahacks](https://github.com/jmazzahacks))
