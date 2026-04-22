#!/usr/bin/env python3
"""Run repository lint checks.

Currently enforces cyclomatic complexity via lizard with a CCN threshold of 10.

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
from pathlib import Path

log = logging.getLogger("lint")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIZARD_THRESHOLD = 10
BASELINE_FILE = PROJECT_ROOT / "tools" / "lizard_baseline.txt"

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


def _build_lizard_command() -> list[str]:
    cmd = [
        "lizard",
        f"--CCN={LIZARD_THRESHOLD}",
        "--warnings_only",
    ]
    for name in sorted(EXCLUDE):
        cmd.append(f"--exclude={name}")
        cmd.append(f"--exclude=*/{name}/*")
    cmd.extend(LIZARD_ROOTS)
    return cmd


def _supports_appimage_extract(binary: str) -> bool:
    result = subprocess.run(
        [binary, "--appimage-version"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repository lint checks")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Accepted for CI symmetry; lint checks are always non-mutating",
    )
    args = parser.parse_args()
    del args

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    binary = shutil.which("lizard")
    if binary is None:
        log.error("lizard not found. Install it to run complexity checks.")
        return 1

    cmd = _build_lizard_command()
    if _supports_appimage_extract(binary):
        cmd.insert(1, "--appimage-extract-and-run")
    log.info("lizard: cyclomatic complexity threshold <= %d", LIZARD_THRESHOLD)
    baseline = _load_baseline()
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True)

    current, stale = _filter_warnings(result.stdout, baseline)

    if current:
        for line in current:
            sys.stdout.write(f"{line}\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
    if stale:
        log.error("Stale lizard baseline entries found:")
        for entry in stale:
            log.error("  %s", entry)
        return 1
    if current:
        log.error("Complexity issues found.")
        return 1

    log.info("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
