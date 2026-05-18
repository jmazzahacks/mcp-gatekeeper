FROM python:3.13-slim

WORKDIR /app

# git is needed at build time to pip-install the api-gatekeeper-api dependency
# from its public GitHub repo. It's a build dep only — purged before the final
# image so the runtime stays minimal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Copy package metadata + source, then install. Doing it in two layers keeps
# code edits from invalidating the dependency layer.
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir . \
    && apt-get purge -y git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 7872

# Production transport. HOST defaults to 127.0.0.1 (safe-by-default) — the
# container is unreachable from the host until an operator opts in via
# `MCP_HOST=0.0.0.0` + `FASTMCP_HOST=0.0.0.0` in their compose env. This
# prevents `docker run -p 7872:7872 …` (without nginx in front) from
# silently exposing the admin-token-wielding MCP to the public internet.
#
# Both env-var names are required because FastMCP's constructor defaults
# override its own env vars — see src/mcp_gatekeeper/server.py for the
# workaround.
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=127.0.0.1
ENV MCP_PORT=7872
ENV FASTMCP_HOST=127.0.0.1
ENV FASTMCP_PORT=7872

# GATEKEEPER_BASE_URL and GATEKEEPER_ADMIN_TOKEN must be supplied at run time
# (docker-compose, kubernetes secret, etc.) — never bake them into the image.

CMD ["mcp-gatekeeper"]
