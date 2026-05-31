#!/bin/bash
# Codegen freshness check for Bazel test integration.
set -euo pipefail
WORKSPACE="${BUILD_WORKSPACE_DIRECTORY:-$(git rev-parse --show-toplevel)}"
# Find the dev formatters: the venv (buildifier installed by `task setup`,
# clang-format from pip) plus /usr/local/bin (CI-installed buildifier).
export PATH="$WORKSPACE/python/.venv/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
cd "$WORKSPACE"
exec python3 tools/generate.py --check
