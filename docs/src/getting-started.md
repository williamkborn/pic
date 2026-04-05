# Getting Started

## Prerequisites

- [Bazel 9](https://bazel.build/) (see `.bazelversion`)
- [QEMU user-static](https://www.qemu.org/) for cross-architecture testing
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip/venv

Toolchains are fetched automatically via [Bootlin](https://toolchains.bootlin.com/) for
Linux cross-compilation (ARMv5, ARMv7, AArch64, MIPS, s390x, x86).

## Quick start

```bash
# Set up Python environment
source sourceme

# Build and stage all blobs + runners
./buildall

# Verify everything works
picblobs verify

# Run the full test suite
./testall
```

## Docker / Podman (no local setup)

A Fedora 43 dev container with all dependencies pre-installed is provided
in `ci/`:

```bash
ci/dev.sh                          # interactive shell
ci/dev.sh python -m picblobs verify   # run a command and exit
```
