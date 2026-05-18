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
import time
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
from mcp.server.fastmcp import Context, FastMCP

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


def _diag_root_handler(label: str) -> None:
    """Bypass the logging system and print the live state of root.handlers[0].

    Records id(handler) so we can detect handler-reinstantiation across calls,
    listener-thread liveness, and queue diagnostics. Used during the Loki-
    silence investigation — if the listener is dead OR the queue is filling
    without draining, records are vanishing inside the handler.
    """
    import sys as _sys
    root = logging.getLogger()
    handlers = root.handlers
    h = handlers[0] if handlers else None
    listener_alive = "n/a"
    diagnostics = "n/a"
    if h is not None:
        listener = getattr(h, "listener", None)
        if listener is not None:
            thread = getattr(listener, "_thread", None)
            listener_alive = thread.is_alive() if thread is not None else "no-thread-attr"
        if hasattr(h, "get_diagnostics"):
            try:
                diagnostics = h.get_diagnostics()
            except Exception as exc:
                diagnostics = f"<get_diagnostics raised {type(exc).__name__}>"
    print(
        f"[startup-diag] {label} "
        f"handler_count={len(handlers)} "
        f"first_class={type(h).__name__ if h else None} "
        f"handler_id={id(h) if h else None} "
        f"listener_alive={listener_alive} "
        f"diagnostics={diagnostics}",
        file=_sys.stderr,
        flush=True,
    )


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[None]:
    """Construct the HTTP client at server start, close it cleanly at stop.

    Replaces the previous lazy-init pattern. `aclose()` in `finally` prevents
    the "Unclosed client session" ResourceWarning on SIGTERM and avoids
    connection-pool leaks if the process is ever restarted in-place. Config
    is loaded here (not at import time) so importing this module from tests
    or tooling doesn't require GATEKEEPER_BASE_URL/TOKEN to be set.
    """
    # In stateless_http=True mode this lifespan fires PER REQUEST (not just
    # once at server startup). Each firing records handler identity + listener
    # state — if the handler_id changes across firings, dictConfig OR something
    # else is reinstantiating the handler per request and the new instance
    # has no listener thread.
    _diag_root_handler("lifespan-enter (stateless: fires per-session)")

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


def _caller_from(ctx: Context) -> tuple[str | None, str | None]:
    """Extract the gatekeeper-issued client identity from request headers.

    The mcp-gatekeeper container sits behind nginx with `auth_request`
    delegated to gatekeeper's /authz endpoint. When gatekeeper authorizes
    a caller, it returns the matched client's id + name as response
    headers, which nginx forwards upstream as `X-Client-ID` and
    `X-Client-Name`. Header names are case-insensitive; Starlette
    normalizes them to lowercase on the request object.

    Returns (None, None) for stdio transport (no HTTP request) or when
    the headers are absent for any other reason — callers must handle
    None gracefully.
    """
    try:
        request = ctx.request_context.request
    except (ValueError, AttributeError):
        # No active request (stdio) or Context outside request scope
        return None, None
    if request is None or not hasattr(request, "headers"):
        return None, None
    return (
        request.headers.get("x-client-id"),
        request.headers.get("x-client-name"),
    )


class _LogToolCall:
    """Async context manager that times a tool call and emits a structured
    log line on exit (success or error).

    Logs ship through the root logger; under byteforge-loki-logging's
    JSON formatter the extra={} fields become first-class JSON keys in
    Loki, queryable with `{application="mcp-gatekeeper"} | json | tool="show_client"`.
    """

    def __init__(self, tool: str, ctx: Context) -> None:
        self._tool = tool
        self._ctx = ctx
        self._start = 0.0
        self._error: str | None = None

    async def __aenter__(self) -> "_LogToolCall":
        self._start = time.monotonic()
        return self

    async def __aexit__(self, exc_type: object, _exc: object, _tb: object) -> None:
        if exc_type is not None and isinstance(exc_type, type):
            self._error = exc_type.__name__
        caller_id, caller_name = _caller_from(self._ctx)
        duration_ms = round((time.monotonic() - self._start) * 1000, 2)
        logger.info(
            "tool_invoked",
            extra={
                "tool": self._tool,
                "caller_id": caller_id,
                "caller_name": caller_name,
                "duration_ms": duration_ms,
                "error": self._error,
            },
        )


@mcp.tool()
async def list_clients(ctx: Context) -> list[ClientSummary]:
    """List every client (API credential) configured on the gatekeeper.

    Each ClientSummary has: client_id, client_name, status (active/suspended/
    revoked), api_key_masked (only first 8 + last 4 chars), created_at and
    updated_at (unix seconds). Shared secrets and full API keys are NEVER
    returned — the gatekeeper redacts them server-side.
    """
    # Fires DURING a tool call — captures handler state at exactly the moment
    # we expect log records to be flowing. If diagnostics shows queue_size
    # growing here, the listener thread isn't draining.
    _diag_root_handler("tool list_clients invoked")
    async with _LogToolCall("list_clients", ctx):
        return await _client().list_clients()


@mcp.tool()
async def list_routes(ctx: Context) -> list[Route]:
    """List every route the gatekeeper enforces.

    Each Route has: route_id, route_pattern (URL pattern, may end in /*),
    domain (exact, wildcard *.example.com, or *), service_name, methods
    (dict of HttpMethod → MethodAuth with auth_required + auth_type),
    created_at and updated_at (unix seconds).
    """
    async with _LogToolCall("list_routes", ctx):
        return await _client().list_routes()


@mcp.tool()
async def list_permissions(ctx: Context) -> list[PermissionSummary]:
    """List every client→route permission grant (denormalized for display).

    Each PermissionSummary joins a ClientPermission with display fields
    from its Client and Route: permission_id, client_id, client_name,
    route_id, route_domain, route_pattern, route_service_name,
    allowed_methods (list of HttpMethod), created_at.
    """
    async with _LogToolCall("list_permissions", ctx):
        return await _client().list_permissions()


@mcp.tool()
async def list_rate_limits(ctx: Context) -> list[RateLimitSummary]:
    """List per-client rate-limit overrides.

    Each RateLimitSummary has: client_id, client_name, requests_per_day,
    created_at, updated_at. Clients using the gatekeeper's default rate
    do NOT appear — only clients with an explicit override.
    """
    async with _LogToolCall("list_rate_limits", ctx):
        return await _client().list_rate_limits()


@mcp.tool()
async def show_client(client_id: str, ctx: Context) -> ClientSummary:
    """Return the single ClientSummary matching client_id, or raise.

    Implemented as a client-side filter over list_clients because the
    gatekeeper admin API has no GET /clients/<id> endpoint.
    """
    async with _LogToolCall("show_client", ctx):
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

    # Bypass-the-logging-system diagnostic, fires before configure_logging.
    import sys as _sys
    print(
        f"[startup-diag] main() entry: DEBUG_LOCAL={debug_mode} "
        f"LOG_LEVEL={log_level}",
        file=_sys.stderr,
        flush=True,
    )

    # MCP_GATEKEEPER_LOKI_APP_TAG lets an operator override the Loki
    # `application` label without rebuilding the image — useful when
    # debugging "logs vanish silently under a specific tag" scenarios
    # (Loki tenant filters, Promtail relabel rules, etc.). Default
    # keeps the documented behavior; set to e.g. "mcp-gatekeeper-v2"
    # to confirm tag-specific filtering at the ingest layer.
    app_tag = os.environ.get("MCP_GATEKEEPER_LOKI_APP_TAG", "mcp-gatekeeper")
    print(
        f"[startup-diag] application_tag={app_tag!r} "
        f"(override env=MCP_GATEKEEPER_LOKI_APP_TAG)",
        file=_sys.stderr,
        flush=True,
    )

    configure_logging(
        application_tag=app_tag,
        debug_local=debug_mode,
        local_level=log_level,
    )

    _diag_root_handler("post-configure_logging (fires once at startup)")

    # Startup self-test for the deployed-PID-1-can't-reach-Loki investigation
    # (Janus admin question #5). Emit ONE record from ONE logger with a
    # known unique marker, then force a synchronous flush of the underlying
    # batch handler. If this record appears in Loki under application=<tag>
    # the lib+net path works in PID 1 and the issue is multi-stream batches.
    # If it doesn't, deployed PID 1 isn't shipping at all, period.
    if not debug_mode:
        import time as _time
        _marker = f"selftest-{int(_time.time())}-{os.getpid()}"
        print(f"[startup-diag] LOKI SELF-TEST marker={_marker} tag={app_tag}", file=_sys.stderr, flush=True)
        logging.getLogger("mcp_gatekeeper.selftest").info(
            "loki_selftest", extra={"marker": _marker, "phase": "startup"}
        )
        # Force the queue listener to drain into LokiBatchHandler, then flush
        # the batch synchronously so the record can't be sitting in a buffer.
        _time.sleep(0.5)
        _root_handlers = logging.getLogger().handlers
        for _h in _root_handlers:
            if hasattr(_h, "flush"):
                try:
                    _h.flush()
                except Exception as _e:
                    print(f"[startup-diag] LOKI SELF-TEST flush raised: {type(_e).__name__}: {_e}", file=_sys.stderr, flush=True)
        _time.sleep(0.5)
        print(f"[startup-diag] LOKI SELF-TEST flush complete; marker={_marker} should now be in Loki", file=_sys.stderr, flush=True)

    # Fail-fast on missing/invalid env vars. The HTTP client is created later,
    # inside lifespan() — Config.from_env() runs again there but env is stable
    # so both calls see the same values.
    config = Config.from_env()

    if config.transport == "stdio":
        # stdio has no uvicorn — JSON-RPC straight over stdin/stdout. The
        # log_config concerns below don't apply; the existing run() path is
        # correct.
        mcp.run(transport="stdio")
        return

    # For streamable-http / sse, drive uvicorn directly so we can pass a
    # log_config that routes uvicorn.access / uvicorn.error through the root
    # logger. FastMCP's mcp.run() constructs uvicorn.Config without
    # log_config=, so uvicorn falls back to its default LOGGING_CONFIG which
    # sets propagate=False on those loggers — HTTP access logs never reach
    # Loki. We bypass FastMCP's run helper but reuse its starlette_http_app /
    # sse_app, so we keep all FastMCP's routing logic intact.
    import asyncio
    import uvicorn

    starlette_app = (
        mcp.streamable_http_app() if config.transport == "streamable-http"
        else mcp.sse_app()
    )
    uv_config = uvicorn.Config(
        starlette_app,
        host=_HOST,
        port=_PORT,
        log_level=log_level.lower(),
        log_config=_uvicorn_log_config_propagating_to_root(),
    )
    asyncio.run(uvicorn.Server(uv_config).serve())


def _uvicorn_log_config_propagating_to_root() -> dict:
    """uvicorn log_config that routes its own loggers through Python root.

    uvicorn's default LOGGING_CONFIG attaches its own StreamHandler to
    `uvicorn`, `uvicorn.access`, and `uvicorn.error` with `propagate=False`
    — those records bypass root and the byteforge-loki-logging handler we
    installed in main(). Setting `handlers: []` + `propagate: True` lets
    them propagate up to root, where they get JSON-formatted and shipped
    to Loki under application=mcp-gatekeeper.

    `disable_existing_loggers: False` is critical — without it dictConfig
    silently wipes byteforge-loki-logging's root configuration as a side
    effect of uvicorn's logging setup.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {
            "uvicorn": {"handlers": [], "level": "INFO", "propagate": True},
            "uvicorn.access": {"handlers": [], "level": "INFO", "propagate": True},
            "uvicorn.error": {"handlers": [], "level": "INFO", "propagate": True},
        },
    }


if __name__ == "__main__":
    main()
