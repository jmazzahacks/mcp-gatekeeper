#!/bin/sh
# Build and publish the mcp-gatekeeper Docker image to GHCR.
# Usage: ./build-publish.sh [--no-cache]
#
# NOTE: pip-installing this image requires the api-gatekeeper-api-python repo
# to exist publicly at https://github.com/jmazzahacks/api-gatekeeper-api-python.
# Push that repo before running this script for the first time, or the
# `pip install .` step inside the Dockerfile will fail.
set -e

REGISTRY="ghcr.io/jmazzahacks/mcp-gatekeeper"

NO_CACHE=""
if [ "$1" = "--no-cache" ]; then
    NO_CACHE="--no-cache"
fi

if [ ! -f VERSION ]; then
    echo "1" > VERSION
fi

CURRENT_VERSION=$(cat VERSION)

case "$CURRENT_VERSION" in
    ''|*[!0-9]*)
        echo "ERROR: VERSION file contains non-numeric value: $CURRENT_VERSION"
        exit 1
        ;;
esac

NEXT_VERSION=$((CURRENT_VERSION + 1))

echo "Building ${REGISTRY}:${NEXT_VERSION}..."

# With `set -e` above, any failed step aborts the script — no per-command
# `$? -ne 0` blocks needed. Add new steps freely without worrying about
# whether you remembered to error-check them.

# --platform linux/amd64 is intentional, NOT a leftover. Production runs on
# amd64 hosts; arm64 contributors (M-series Macs, ARM cloud) will get an
# emulated build — that's correct, do not remove this flag. Matches the
# convention used by gatekeeper-backend/build-publish.sh.
docker build \
    --platform linux/amd64 \
    $NO_CACHE \
    -t "${REGISTRY}:${NEXT_VERSION}" \
    .

docker tag "${REGISTRY}:${NEXT_VERSION}" "${REGISTRY}:latest"

echo "Pushing ${REGISTRY}:${NEXT_VERSION}..."
docker push "${REGISTRY}:${NEXT_VERSION}"

echo "Pushing ${REGISTRY}:latest..."
docker push "${REGISTRY}:latest"

# Only reached if every step above succeeded.
echo "$NEXT_VERSION" > VERSION
echo "Published ${REGISTRY}:${NEXT_VERSION} and :latest"
