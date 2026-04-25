#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
export PICBLOBS_REQUIRE_LINT_TOOLS=1
exec bazel build --config=lint //src/... //tests/...
