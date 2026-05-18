import pytest

from mcp_gatekeeper.config import Config, read_bind


def test_from_env_loads_all_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEKEEPER_BASE_URL", "https://gk.example.com/")
    monkeypatch.setenv("GATEKEEPER_ADMIN_TOKEN", "tok")
    monkeypatch.setenv("GATEKEEPER_REQUEST_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")

    config = Config.from_env()

    assert config.base_url == "https://gk.example.com"
    assert config.admin_token == "tok"
    assert config.request_timeout_seconds == 7.5
    assert config.transport == "streamable-http"


def test_missing_base_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GATEKEEPER_BASE_URL", raising=False)
    monkeypatch.setenv("GATEKEEPER_ADMIN_TOKEN", "tok")
    with pytest.raises(RuntimeError, match="GATEKEEPER_BASE_URL"):
        Config.from_env()


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEKEEPER_BASE_URL", "https://gk.example.com")
    monkeypatch.delenv("GATEKEEPER_ADMIN_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GATEKEEPER_ADMIN_TOKEN"):
        Config.from_env()


def test_bad_transport_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEKEEPER_BASE_URL", "https://gk.example.com")
    monkeypatch.setenv("GATEKEEPER_ADMIN_TOKEN", "tok")
    monkeypatch.setenv("MCP_TRANSPORT", "telegrams")
    with pytest.raises(RuntimeError, match="MCP_TRANSPORT"):
        Config.from_env()


def test_default_transport_is_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEKEEPER_BASE_URL", "https://gk.example.com")
    monkeypatch.setenv("GATEKEEPER_ADMIN_TOKEN", "tok")
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    config = Config.from_env()
    assert config.transport == "stdio"


def test_bad_timeout_raises_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEKEEPER_BASE_URL", "https://gk.example.com")
    monkeypatch.setenv("GATEKEEPER_ADMIN_TOKEN", "tok")
    monkeypatch.setenv("GATEKEEPER_REQUEST_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(RuntimeError, match="GATEKEEPER_REQUEST_TIMEOUT_SECONDS") as exc_info:
        Config.from_env()
    # `raise ... from None` should suppress the underlying ValueError in tracebacks.
    assert exc_info.value.__suppress_context__ is True


def test_bad_port_raises_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_PORT", "not-a-number")
    monkeypatch.delenv("FASTMCP_PORT", raising=False)
    with pytest.raises(RuntimeError, match="MCP_PORT/FASTMCP_PORT") as exc_info:
        read_bind()
    assert exc_info.value.__suppress_context__ is True


def test_fastmcp_host_wins_over_mcp_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # FastMCP itself reads FASTMCP_* internally; we have to match its view.
    # If both are set, FASTMCP_HOST is the source of truth.
    monkeypatch.setenv("MCP_HOST", "from-mcp-var")
    monkeypatch.setenv("FASTMCP_HOST", "from-fastmcp-var")
    monkeypatch.delenv("MCP_PORT", raising=False)
    monkeypatch.delenv("FASTMCP_PORT", raising=False)
    host, _ = read_bind()
    assert host == "from-fastmcp-var"


def test_fastmcp_port_wins_over_mcp_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_PORT", "1111")
    monkeypatch.setenv("FASTMCP_PORT", "2222")
    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.delenv("FASTMCP_HOST", raising=False)
    _, port = read_bind()
    assert port == 2222
