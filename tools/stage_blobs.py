#!/usr/bin/env python3
"""Stage built .so blobs and test runners into the Python package tree.

Builds all blob and runner targets for all platform configs via Bazel,
then copies outputs into:
  python/picblobs/_blobs/{os}/{arch}/{name}.so
  python/picblobs/_runners/{os}/{arch}/runner

Usage:
    python tools/stage_blobs.py                       # build + stage all
    python tools/stage_blobs.py --targets hello        # one blob type
    python tools/stage_blobs.py --configs linux:x86_64 # one platform
    python tools/stage_blobs.py --no-runners           # blobs only
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry import platform_configs

_sys.path.pop(0)

log = logging.getLogger("picblobs.stage")

# Derived from the canonical registry (tools/registry.py).
PLATFORM_CONFIGS = platform_configs()

# Bazel label templates.
BLOB_LABEL_TEMPLATE = "//src/payload:{name}"
RUNNER_LABEL = "//tests/runners/{runner_type}:runner"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BLOB_DIR = PROJECT_ROOT / "python" / "picblobs" / "_blobs"
RUNNER_DIR = PROJECT_ROOT / "python" / "picblobs" / "_runners"


def discover_blob_targets() -> list[str]:
    """Discover blob target names from src/payload/BUILD.bazel."""
    build_file = PROJECT_ROOT / "src" / "payload" / "BUILD.bazel"
    if not build_file.exists():
        return ["hello"]
    targets = []
    for match in re.finditer(
        r'pic_blob\(\s*name\s*=\s*"([^"]+)"', build_file.read_text()
    ):
        targets.append(match.group(1))
    return targets or ["hello"]


def bazel_build(config: str, labels: list[str]) -> bool:
    """Run bazel build for a config+labels. Returns True on success."""
    cmd = ["bazel", "build", f"--config={config}"] + labels
    result = subprocess.run(cmd, capture_output=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        for line in result.stderr.decode().splitlines():
            if "error" in line.lower():
                log.error("    %s", line.strip())
        return False
    return True


def stage_file(src: Path, dest: Path, executable: bool = False) -> bool:
    """Copy a file, handling read-only destinations."""
    if not src.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.chmod(stat.S_IWUSR | stat.S_IRUSR)
        dest.unlink()
    shutil.copy2(src, dest)
    if executable:
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def find_bazel_output(label: str, extension: str) -> Path:
    """Convert a Bazel label to its output path in bazel-bin/."""
    pkg, name = label.lstrip("/").split(":")
    return PROJECT_ROOT / "bazel-bin" / pkg / f"{name}{extension}"


def build_and_stage(
    targets: list[str],
    configs: list[str],
    no_runners: bool = False,
) -> tuple[int, int]:
    """Build and stage blobs+runners. Returns (passed, total)."""
    total = 0
    passed = 0

    for config_key in configs:
        if config_key not in PLATFORM_CONFIGS:
            log.error("Unknown config: %s", config_key)
            continue

        bazel_config, runner_type = PLATFORM_CONFIGS[config_key]
        os_name, arch_name = config_key.split(":")

        labels = []
        for blob_name in targets:
            labels.append(BLOB_LABEL_TEMPLATE.format(name=blob_name))
        if not no_runners:
            labels.append(RUNNER_LABEL.format(runner_type=runner_type))

        log.info("  [%s] building... ", config_key)
        if not bazel_build(bazel_config, labels):
            log.error("  [%s] BUILD FAIL", config_key)
            total += len(targets) + (0 if no_runners else 1)
            continue
        log.info("  [%s] OK", config_key)

        for blob_name in targets:
            total += 1
            label = BLOB_LABEL_TEMPLATE.format(name=blob_name)
            src = find_bazel_output(label, ".so")
            dest = BLOB_DIR / os_name / arch_name / f"{blob_name}.so"

            tag = f"    {blob_name}.so -> {os_name}/{arch_name}"
            if stage_file(src, dest):
                log.info("%-50s OK", tag)
                passed += 1
            else:
                log.error("%-50s NOT FOUND: %s", tag, src)

        if not no_runners:
            total += 1
            runner_label = RUNNER_LABEL.format(runner_type=runner_type)
            src = find_bazel_output(runner_label, ".bin")
            dest = RUNNER_DIR / runner_type / arch_name / "runner"

            tag = f"    runner -> {runner_type}/{arch_name}"
            if stage_file(src, dest, executable=True):
                log.info("%-50s OK", tag)
                passed += 1
            else:
                log.error("%-50s NOT FOUND: %s", tag, src)

    return passed, total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage blobs and runners into package tree"
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        default=None,
        help="Blob target names (default: auto-discovered from BUILD.bazel)",
    )
    parser.add_argument(
        "--configs",
        nargs="*",
        default=list(PLATFORM_CONFIGS.keys()),
        help="Platform configs as os:arch (default: all)",
    )
    parser.add_argument(
        "--no-runners",
        action="store_true",
        help="Skip building/staging test runners",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if args.targets is None:
        args.targets = discover_blob_targets()

    passed, total = build_and_stage(args.targets, args.configs, args.no_runners)

    log.info("%d/%d staged", passed, total)
    if passed < total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
