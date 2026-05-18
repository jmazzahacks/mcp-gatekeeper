import pytest

from mcp_gatekeeper.config import Config


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
