#!/usr/bin/env python3
"""Format all project source files.

Runs clang-format on C/H files and Ruff format on Python files.
Excludes build artifacts, venvs, and external dependencies.

Usage:
    python tools/fmt.py            # format in place
    python tools/fmt.py --check    # exit 1 if anything would change (for CI)
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("fmt")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories to search for source files.
C_ROOTS = ["src", "tests"]
PY_ROOTS = [
    "python/picblobs",
    "python/tests",
    "python_cli/picblobs_cli",
    "python_cli/tests",
    "tools",
]

# Directories to exclude (relative to project root).
EXCLUDE = {
    "bazel-bin",
    "bazel-out",
    "bazel-testlogs",
    "bazel-picblobs",
    ".venv",
    "__pycache__",
    ".cache",
    "node_modules",
}


def _find_files(roots: list[str], extensions: set[str]) -> list[Path]:
    """Find all files with given extensions under roots, excluding artifacts."""
    files = []
    for root_name in roots:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if any(part in EXCLUDE for part in path.relative_to(PROJECT_ROOT).parts):
                continue
            if path.suffix in extensions and path.is_file():
                files.append(path)
    return sorted(files)


def _run_formatter(
    name: str,
    cmd: list[str],
    files: list[Path],
    check: bool,
) -> bool:
    """Run a formatter on a list of files. Returns True if all clean."""
    if not files:
        return True

    binary = shutil.which(cmd[0])
    if binary is None:
        log.warning("%s not found, skipping %d files", cmd[0], len(files))
        return True

    full_cmd = cmd + [str(f) for f in files]
    log.info("%s: %d files", name, len(files))
    log.debug("  %s", " ".join([*cmd[:3], "..."]))

    result = subprocess.run(full_cmd, capture_output=True, check=False, text=True)

    if result.returncode != 0:
        if check:
            # Show which files need formatting.
            if result.stdout:
                for line in result.stdout.strip().splitlines():
                    log.error("  %s", line)
            if result.stderr:
                for line in result.stderr.strip().splitlines():
                    log.error("  %s", line)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Format all project source files")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check formatting without modifying (exit 1 if unformatted)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    c_files = _find_files(C_ROOTS, {".c", ".h"})
    py_files = _find_files(PY_ROOTS, {".py"})

    ok = True

    # C/H files: clang-format
    if c_files:
        if args.check:
            c_cmd = ["clang-format", "--dry-run", "--Werror"]
        else:
            c_cmd = ["clang-format", "-i"]
        if not _run_formatter("clang-format", c_cmd, c_files, args.check):
            ok = False

    # Python files: ruff format
    if py_files:
        py_cmd = ["ruff", "format", "--check"] if args.check else ["ruff", "format"]
        if not _run_formatter("ruff", py_cmd, py_files, args.check):
            ok = False

    if ok:
        log.info("ok")
    else:
        if args.check:
            log.error("Formatting issues found. Run: python tools/fmt.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
