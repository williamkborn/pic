#!/usr/bin/env bash
# Drop into the picblobs dev container with the source tree mounted.
#
# Usage:
#   ci/dev.sh              # interactive shell
#   ci/dev.sh make test    # run a command and exit

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="picblobs-dev"

# Pick whichever container runtime is available.
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    RUNTIME=docker
elif command -v podman &>/dev/null; then
    RUNTIME=podman
else
    echo "error: neither docker nor podman found" >&2
    exit 1
fi

# Build the image if it doesn't exist.
if ! $RUNTIME image exists "$IMAGE" 2>/dev/null; then
    echo "Building $IMAGE ..."
    $RUNTIME build -t "$IMAGE" -f "$SCRIPT_DIR/Dockerfile" "$PROJECT_ROOT"
fi

# Mount flags: :Z for SELinux relabelling (harmless on non-SELinux hosts).
MOUNT=(-v "$PROJECT_ROOT:/workspace:Z")

if [ $# -eq 0 ]; then
    exec $RUNTIME run --rm -it "${MOUNT[@]}" "$IMAGE"
else
    exec $RUNTIME run --rm "${MOUNT[@]}" "$IMAGE" bash -c "cd /workspace && $*"
fi
