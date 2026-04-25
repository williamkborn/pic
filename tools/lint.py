#!/usr/bin/env python3
"""Run repository lint checks.

Enforces Ruff linting for Python plus cyclomatic complexity via lizard.

Usage:
    python tools/lint.py            # run lint checks
    python tools/lint.py --check    # accepted for CI symmetry with fmt.py
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from quality_paths import PROJECT_ROOT, collect_files

log = logging.getLogger("lint")

if TYPE_CHECKING:
    from pathlib import Path

LIZARD_THRESHOLD = 10
BASELINE_FILE = PROJECT_ROOT / "tools/lizard_baseline.txt"
RUFF_ROOTS = ["python/picblobs", "python/tests", "python_cli", "tools"]

LIZARD_ROOTS = ["src", "tests", "python", "python_cli", "tools"]
EXCLUDE = {
    "bazel-bin",
    "bazel-out",
    "bazel-testlogs",
    "bazel-pic",
    "bazel-picblobs",
    ".venv",
    "__pycache__",
    ".cache",
    "node_modules",
    "dist",
    "build",
}


def _relativize(paths: list[Path]) -> list[str]:
    return [str(path.relative_to(PROJECT_ROOT)) for path in paths]


def _build_lizard_command(paths: list[Path] | None = None) -> list[str]:
    cmd = [
        "lizard",
        f"--CCN={LIZARD_THRESHOLD}",
        "--warnings_only",
    ]
    for name in sorted(EXCLUDE):
        cmd.append(f"--exclude={name}")
        cmd.append(f"--exclude=*/{name}/*")
    cmd.extend(_relativize(paths) if paths is not None else LIZARD_ROOTS)
    return cmd


def _build_ruff_command(paths: list[Path] | None = None) -> list[str]:
    return ["ruff", "check", *(_relativize(paths) if paths is not None else RUFF_ROOTS)]


def _supports_appimage_extract(binary: str) -> bool:
    result = subprocess.run(
        [binary, "--appimage-version"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _run_ruff_check(paths: list[Path] | None = None) -> int:
    if paths == []:
        log.info("ruff: no matching Python files")
        return 0

    binary = shutil.which("ruff")
    if binary is None:
        log.error("ruff not found. Install it to run Python lint checks.")
        return 1

    cmd = _build_ruff_command(paths)
    log.info("ruff: Python lint checks")
    result = subprocess.run(
        cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, check=False
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


def _run_lizard_check(paths: list[Path] | None, *, check_stale: bool) -> int:
    binary = shutil.which("lizard")
    if binary is None:
        log.error("lizard not found. Install it to run complexity checks.")
        return 1

    cmd = _build_lizard_command(paths)
    if _supports_appimage_extract(binary):
        cmd.insert(1, "--appimage-extract-and-run")
    log.info("lizard: cyclomatic complexity threshold <= %d", LIZARD_THRESHOLD)
    baseline = _load_baseline()
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    current, stale = _filter_warnings(result.stdout, baseline)

    if current:
        for line in current:
            sys.stdout.write(f"{line}\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
    if stale and check_stale:
        log.error("Stale lizard baseline entries found:")
        for entry in stale:
            log.error("  %s", entry)
        return 1
    if current:
        log.error("Complexity issues found.")
        return 1

    log.info("ok")
    return 0


def _load_baseline() -> set[str]:
    if not BASELINE_FILE.exists():
        return set()
    return {
        line.strip()
        for line in BASELINE_FILE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _warning_key(line: str) -> str | None:
    match = re.match(r"^(.*?):\d+: warning: ([^( ]+)\s+has\s+", line)
    if not match:
        return None
    path, func = match.groups()
    return f"{path}:{func}"


def _filter_warnings(stdout: str, baseline: set[str]) -> tuple[list[str], list[str]]:
    current: list[str] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        key = _warning_key(line)
        if key is None:
            continue
        seen.add(key)
        if key not in baseline:
            current.append(line)
    stale = sorted(baseline - seen)
    return current, stale


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repository lint checks")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Accepted for CI symmetry; lint checks are always non-mutating",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional files or directories to lint. Defaults to repo source roots.",
    )
    return parser.parse_args()


def _collect_targets(paths: list[str]) -> tuple[list[Path], list[Path]]:
    ruff_paths = collect_files(
        paths,
        roots=RUFF_ROOTS,
        extensions={".py"},
        exclude=EXCLUDE,
    )
    lizard_paths = collect_files(
        paths,
        roots=LIZARD_ROOTS,
        extensions={".c", ".h", ".py"},
        exclude=EXCLUDE,
    )
    return ruff_paths, lizard_paths


def main() -> int:
    args = _parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    ruff_paths, lizard_paths = _collect_targets(args.paths)

    if not ruff_paths and not lizard_paths and args.paths:
        log.info("No matching files.")
        return 0

    if _run_ruff_check(paths=ruff_paths if args.paths else None) != 0:
        log.error("Ruff issues found.")
        return 1

    if not lizard_paths and args.paths:
        log.info("ok")
        return 0

    return _run_lizard_check(
        lizard_paths if args.paths else None,
        check_stale=not args.paths,
    )


if __name__ == "__main__":
    raise SystemExit(main())
