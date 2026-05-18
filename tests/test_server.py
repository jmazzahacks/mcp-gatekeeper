"""Tests for the MCP server's non-trivial tool wrappers + invariant pins.

Most @mcp.tool() functions in server.py are 1-line delegators to the
api-gatekeeper-api client (tested in that lib's own suite). `show_client`
is the exception — it has real branching logic so it gets its own coverage.

The stub_client fixture monkeypatches the module-level _CLIENT global with
an AsyncMock, bypassing the lifespan that would normally set it.

Since the lib's v0.3.0 refactor, tools return typed dataclasses from
api-gatekeeper-models rather than raw dicts. These tests assert on attribute
access (e.g. result.client_id) not dict access — pinning the new contract.

Also enforces the project's core invariant: no write HTTP methods may
appear in server.py (see test_server_module_has_no_write_http_calls).
"""
import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from api_gatekeeper_models import ClientStatus, ClientSummary

from mcp_gatekeeper import server
from mcp_gatekeeper.server import show_client


def _make_client_summary(client_id: str, client_name: str = "test") -> ClientSummary:
    return ClientSummary(
        client_id=client_id,
        client_name=client_name,
        status=ClientStatus.ACTIVE,
        api_key_masked="abcd1234…wxyz",
        created_at=1_700_000_000,
        updated_at=1_700_000_000,
    )


@pytest.fixture
def stub_client(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    stub = AsyncMock()
    monkeypatch.setattr(server, "_CLIENT", stub)
    return stub


async def test_show_client_finds_by_client_id(stub_client: AsyncMock) -> None:
    stub_client.list_clients.return_value = [
        _make_client_summary("abc", client_name="the-one"),
        _make_client_summary("xyz", client_name="other"),
    ]
    result = await show_client("abc")
    assert isinstance(result, ClientSummary)
    assert result.client_id == "abc"
    assert result.client_name == "the-one"


async def test_show_client_raises_when_not_found(stub_client: AsyncMock) -> None:
    stub_client.list_clients.return_value = [
        _make_client_summary("other"),
    ]
    with pytest.raises(ValueError, match="no client with id 'missing'"):
        await show_client("missing")


async def test_show_client_returns_first_match_when_duplicates(
    stub_client: AsyncMock,
) -> None:
    # Edge case: if the gatekeeper ever returns two records with the same id
    # (it shouldn't, but defending the loop's first-match semantics).
    stub_client.list_clients.return_value = [
        _make_client_summary("abc", client_name="first"),
        _make_client_summary("abc", client_name="second"),
    ]
    result = await show_client("abc")
    assert result.client_name == "first"


def test_server_module_has_no_write_http_calls() -> None:
    """Mechanical enforcement of the read-only invariant.

    server.py must not contain any HTTP write-method calls (.post(),
    .put(), .delete(), .patch()). If you're seeing this fail, you're
    about to add a tool that mutates the gatekeeper — and that's
    explicitly out of scope for this project. See the module docstring
    and CLAUDE.md.

    Implemented via AST walk rather than regex so that the word
    'delete' or 'patch' appearing in a docstring or comment does NOT
    trip the test — only real method calls do.
    """
    server_path = Path(server.__file__)
    tree = ast.parse(server_path.read_text())

    forbidden = {"post", "put", "delete", "patch"}
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in forbidden:
                found.append((node.func.attr, node.lineno))

    assert not found, (
        f"server.py:{found} — read-only invariant violated. "
        "mcp-gatekeeper must not call HTTP write methods. "
        "See module docstring + CLAUDE.md."
    )
