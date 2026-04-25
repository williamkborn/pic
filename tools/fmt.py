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
from typing import TYPE_CHECKING

from quality_paths import collect_files

log = logging.getLogger("fmt")

if TYPE_CHECKING:
    from pathlib import Path

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
        log.error("%s not found. Install it to format %d files.", cmd[0], len(files))
        return False

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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Format all project source files")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check formatting without modifying (exit 1 if unformatted)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional files or directories to format. Defaults to repo source roots.",
    )
    return parser.parse_args()


def _collect_targets(paths: list[str]) -> tuple[list[Path], list[Path]]:
    c_files = collect_files(
        paths,
        roots=C_ROOTS,
        extensions={".c", ".h"},
        exclude=EXCLUDE,
    )
    py_files = collect_files(
        paths,
        roots=PY_ROOTS,
        extensions={".py"},
        exclude=EXCLUDE,
    )
    return c_files, py_files


def _format_c_files(files: list[Path], *, check: bool) -> bool:
    if not files:
        return True
    cmd = ["clang-format", "--dry-run", "--Werror"] if check else ["clang-format", "-i"]
    return _run_formatter("clang-format", cmd, files, check)


def _format_python_files(files: list[Path], *, check: bool) -> bool:
    if not files:
        return True
    cmd = ["ruff", "format", "--check"] if check else ["ruff", "format"]
    return _run_formatter("ruff", cmd, files, check)


def main() -> int:
    args = _parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    c_files, py_files = _collect_targets(args.paths)

    if not c_files and not py_files:
        log.info("No matching files.")
        return 0

    ok = _format_c_files(c_files, check=args.check)
    ok = _format_python_files(py_files, check=args.check) and ok

    if ok:
        log.info("ok")
    else:
        if args.check:
            log.error("Formatting issues found. Run: python tools/fmt.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
