"""Configuration loaded from environment variables."""
import os
from dataclasses import dataclass


def read_bind() -> tuple[str, int]:
    """Read host/port from env with FastMCP-aware precedence + defaults.

    Single source of truth: called by Config.from_env() AND by the FastMCP
    constructor at module-import time in server.py. FastMCP's pydantic-settings
    defaults override its own env vars, so this same logic has to run in two
    places; centralizing it here keeps them from drifting apart.

    Precedence: FASTMCP_* wins over MCP_* (because FastMCP itself reads the
    FASTMCP_* names internally and we have to match its view of the world).
    """
    host = os.environ.get("FASTMCP_HOST", os.environ.get("MCP_HOST", "127.0.0.1"))
    port_raw = os.environ.get("FASTMCP_PORT", os.environ.get("MCP_PORT", "7872"))
    try:
        port = int(port_raw)
    except ValueError:
        raise RuntimeError(
            f"MCP_PORT/FASTMCP_PORT must be an integer, got: {port_raw!r}"
        ) from None
    return host, port


@dataclass(frozen=True)
class Config:
    base_url: str
    admin_token: str
    request_timeout_seconds: float
    transport: str
    host: str
    port: int

    @staticmethod
    def from_env() -> "Config":
        base_url = os.environ.get("GATEKEEPER_BASE_URL", "").rstrip("/")
        if not base_url:
            raise RuntimeError(
                "GATEKEEPER_BASE_URL is required (e.g. https://gatekeeper.example.com)"
            )

        admin_token = os.environ.get("GATEKEEPER_ADMIN_TOKEN", "")
        if not admin_token:
            raise RuntimeError(
                "GATEKEEPER_ADMIN_TOKEN is required (Aegis bearer token for a "
                "user with console-admin role on the target gatekeeper)"
            )

        timeout_raw = os.environ.get("GATEKEEPER_REQUEST_TIMEOUT_SECONDS", "10")
        try:
            timeout = float(timeout_raw)
        except ValueError:
            raise RuntimeError(
                f"GATEKEEPER_REQUEST_TIMEOUT_SECONDS must be a number, got: {timeout_raw!r}"
            ) from None

        transport = os.environ.get("MCP_TRANSPORT", "stdio")
        if transport not in {"stdio", "streamable-http", "sse"}:
            raise RuntimeError(
                f"MCP_TRANSPORT must be one of stdio, streamable-http, sse — got: {transport!r}"
            )

        host, port = read_bind()

        return Config(
            base_url=base_url,
            admin_token=admin_token,
            request_timeout_seconds=timeout,
            transport=transport,
            host=host,
            port=port,
        )
