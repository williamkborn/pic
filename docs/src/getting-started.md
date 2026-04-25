# Getting Started

## Prerequisites

- [Bazel 9](https://bazel.build/) (see `.bazelversion`)
- [QEMU user-static](https://www.qemu.org/) for cross-architecture testing
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip/venv
- `clang-tidy` for full C lint (`pre-push` / `tools/c_lint_check.sh`)

Toolchains are fetched automatically via [Bootlin](https://toolchains.bootlin.com/) for
Linux cross-compilation (ARMv5, ARMv7, AArch64, MIPS, s390x, x86).

## Quick start

```bash
# Set up Python environment
source sourceme

# Build and stage all blobs + runners
./buildall

# Verify everything works
picblobs-cli verify

# Run the full test suite
./testall
```

`source sourceme` also installs the repo's Git hooks with `lefthook`, so local
formatting and lint checks start running automatically on `git commit` and
`git push`.

## Docker / Podman (no local setup)

A Fedora 43 dev container with all dependencies pre-installed is provided
in `ci/`:

```bash
ci/dev.sh                          # interactive shell
ci/dev.sh python -m picblobs_cli verify   # run a command and exit
```
