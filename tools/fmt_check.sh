#!/bin/bash
# Format check for Bazel test integration.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd "${BUILD_WORKSPACE_DIRECTORY:-$(git rev-parse --show-toplevel)}"
exec python3 tools/fmt.py --check
