#!/bin/bash
# Codegen freshness check for Bazel test integration.
set -euo pipefail
WORKSPACE="${BUILD_WORKSPACE_DIRECTORY:-$(git rev-parse --show-toplevel)}"
# Find the dev formatters installed by `task setup`.
export PATH="$WORKSPACE/python/.venv/bin:$HOME/.local/bin:$PATH"
cd "$WORKSPACE"
exec python3 tools/generate.py --check
