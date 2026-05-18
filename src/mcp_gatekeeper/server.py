"""MCP server exposing read-only access to an ApiGatekeeper instance.

Tools surface gatekeeper's /api/admin GET endpoints — listing clients, routes,
permissions, and rate limits, plus a client-side filter helper for inspecting
one client. There are no write tools by design.

All HTTP work is delegated to the api-gatekeeper-api library (the official
Python client) so that the gatekeeper API contract has a single source of
truth across consumers.
"""
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from api_gatekeeper_api import GatekeeperClient
from api_gatekeeper_models import (
    ClientSummary,
    PermissionSummary,
    RateLimitSummary,
    Route,
)
from byteforge_loki_logging import configure_logging
from mcp.server.fastmcp import FastMCP

from mcp_gatekeeper.config import Config, read_bind

logger = logging.getLogger(__name__)

# Set by `lifespan()` when mcp.run() starts; cleared when it stops. Tools
# read it via `_client()` which raises if invoked outside lifespan scope.
_CLIENT: GatekeeperClient | None = None


def _client() -> GatekeeperClient:
    if _CLIENT is None:
        raise RuntimeError(
            "MCP lifespan is not active — _client() called outside mcp.run()."
        )
    return _CLIENT


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[None]:
    """Construct the HTTP client at server start, close it cleanly at stop.

    Replaces the previous lazy-init pattern. `aclose()` in `finally` prevents
    the "Unclosed client session" ResourceWarning on SIGTERM and avoids
    connection-pool leaks if the process is ever restarted in-place. Config
    is loaded here (not at import time) so importing this module from tests
    or tooling doesn't require GATEKEEPER_BASE_URL/TOKEN to be set.
    """
    global _CLIENT
    config = Config.from_env()
    _CLIENT = GatekeeperClient(
        base_url=config.base_url,
        admin_api_key=config.admin_api_key,
        timeout=config.request_timeout_seconds,
    )
    try:
        yield
    finally:
        await _CLIENT.aclose()
        _CLIENT = None


# Host/port are read here at module-load time. For stdio they're unused — the
# small extra env read is fine. For streamable-http/sse this MUST happen in the
# constructor: FastMCP's pydantic-settings defaults override the env vars
# otherwise, leaving the server bound to 127.0.0.1 inside the container.
# stateless_http=True is required behind a reverse proxy so Mcp-Session-Id
# header loss doesn't break clients.
_HOST, _PORT = read_bind()

mcp = FastMCP(
    "mcp-gatekeeper",
    instructions=(
        "Read-only inspection of an ApiGatekeeper instance. Use list_clients, "
        "list_routes, list_permissions, and list_rate_limits to enumerate the "
        "current configuration. Use show_client to inspect one client. There "
        "are no tools that mutate the gatekeeper — for changes, the operator "
        "must use the gatekeeper management scripts directly."
    ),
    host=_HOST,
    port=_PORT,
    stateless_http=True,
    lifespan=lifespan,
)


@mcp.tool()
async def list_clients() -> list[ClientSummary]:
    """List every client (API credential) configured on the gatekeeper.

    Each ClientSummary has: client_id, client_name, status (active/suspended/
    revoked), api_key_masked (only first 8 + last 4 chars), created_at and
    updated_at (unix seconds). Shared secrets and full API keys are NEVER
    returned — the gatekeeper redacts them server-side.
    """
    return await _client().list_clients()


@mcp.tool()
async def list_routes() -> list[Route]:
    """List every route the gatekeeper enforces.

    Each Route has: route_id, route_pattern (URL pattern, may end in /*),
    domain (exact, wildcard *.example.com, or *), service_name, methods
    (dict of HttpMethod → MethodAuth with auth_required + auth_type),
    created_at and updated_at (unix seconds).
    """
    return await _client().list_routes()


@mcp.tool()
async def list_permissions() -> list[PermissionSummary]:
    """List every client→route permission grant (denormalized for display).

    Each PermissionSummary joins a ClientPermission with display fields
    from its Client and Route: permission_id, client_id, client_name,
    route_id, route_domain, route_pattern, route_service_name,
    allowed_methods (list of HttpMethod), created_at.
    """
    return await _client().list_permissions()


@mcp.tool()
async def list_rate_limits() -> list[RateLimitSummary]:
    """List per-client rate-limit overrides.

    Each RateLimitSummary has: client_id, client_name, requests_per_day,
    created_at, updated_at. Clients using the gatekeeper's default rate
    do NOT appear — only clients with an explicit override.
    """
    return await _client().list_rate_limits()


@mcp.tool()
async def show_client(client_id: str) -> ClientSummary:
    """Return the single ClientSummary matching client_id, or raise.

    Implemented as a client-side filter over list_clients because the
    gatekeeper admin API has no GET /clients/<id> endpoint.
    """
    clients = await _client().list_clients()
    for client in clients:
        if client.client_id == client_id:
            return client
    raise ValueError(f"no client with id {client_id!r}")


def main() -> None:
    # Loki logging via byteforge-loki-logging. Modes:
    #   DEBUG_LOCAL=true  — console logs only (local dev, no Loki connection)
    #   DEBUG_LOCAL=false — async structured JSON shipped to Loki under the
    #                        application=mcp-gatekeeper label, with stdout
    #                        fallback if Loki is unreachable at startup
    # The Loki label `application` (NOT `service` or `app`) matches the rest
    # of the api-gatekeeper deployment so filters like
    # `{application=~"api-gatekeeper|mcp-gatekeeper"}` work across services.
    #
    # Replaces the previous logging.basicConfig() — configure_logging()
    # installs its own handler on the root logger.
    debug_mode = os.environ.get("DEBUG_LOCAL", "true").lower() == "true"
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    configure_logging(
        application_tag="mcp-gatekeeper",
        debug_local=debug_mode,
        local_level=log_level,
    )

    # Fail-fast on missing/invalid env vars. The HTTP client is created later,
    # inside lifespan() — Config.from_env() runs again there but env is stable
    # so both calls see the same values.
    config = Config.from_env()
    mcp.run(transport=config.transport)


if __name__ == "__main__":
    main()
