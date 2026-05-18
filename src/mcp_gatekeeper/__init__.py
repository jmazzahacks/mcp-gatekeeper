"""Read-only MCP server for ApiGatekeeper instances."""
from importlib.metadata import version

# Single source of truth: read from installed package metadata. pyproject.toml
# [project].version is canonical.
__version__ = version("mcp-gatekeeper")
