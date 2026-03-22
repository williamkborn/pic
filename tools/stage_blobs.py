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
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

# Map of os:arch → (bazel config name, runner type)
PLATFORM_CONFIGS = {
    "linux:x86_64": ("linux_x86_64", "linux"),
    "linux:i686": ("linux_i686", "linux"),
    "linux:aarch64": ("linux_aarch64", "linux"),
    "linux:armv5_arm": ("linux_armv5_arm", "linux"),
    "linux:mipsel32": ("linux_mipsel32", "linux"),
    "linux:mipsbe32": ("linux_mipsbe32", "linux"),
}

# Bazel label templates.
BLOB_LABEL_TEMPLATE = "//src/payload:{name}"
RUNNER_LABEL = "//tests/runners/{runner_type}:runner"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BLOB_DIR = PROJECT_ROOT / "python" / "picblobs" / "_blobs"
RUNNER_DIR = PROJECT_ROOT / "python" / "picblobs" / "_runners"


def _bazel_build(config: str, labels: list[str]) -> bool:
    """Run bazel build for a config+labels. Returns True on success."""
    cmd = ["bazel", "build", f"--config={config}"] + labels
    result = subprocess.run(cmd, capture_output=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        for line in result.stderr.decode().splitlines():
            if "error" in line.lower():
                print(f"    {line.strip()}", file=sys.stderr)
        return False
    return True


def _stage_file(src: Path, dest: Path, executable: bool = False) -> bool:
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


def _find_bazel_output(label: str, extension: str) -> Path:
    """Convert a Bazel label to its output path in bazel-bin/."""
    # //src/payload:hello → src/payload/hello{extension}
    pkg, name = label.lstrip("/").split(":")
    return PROJECT_ROOT / "bazel-bin" / pkg / f"{name}{extension}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage blobs and runners into package tree")
    parser.add_argument(
        "--targets", nargs="*", default=["hello"],
        help="Blob target names (default: hello)",
    )
    parser.add_argument(
        "--configs", nargs="*", default=list(PLATFORM_CONFIGS.keys()),
        help="Platform configs as os:arch (default: all)",
    )
    parser.add_argument(
        "--no-runners", action="store_true",
        help="Skip building/staging test runners",
    )
    args = parser.parse_args()

    total = 0
    passed = 0

    for config_key in args.configs:
        if config_key not in PLATFORM_CONFIGS:
            print(f"Unknown config: {config_key}", file=sys.stderr)
            continue

        bazel_config, runner_type = PLATFORM_CONFIGS[config_key]
        os_name, arch_name = config_key.split(":")

        # Build all blob targets + runner for this platform in one bazel invocation.
        labels = []
        for blob_name in args.targets:
            labels.append(BLOB_LABEL_TEMPLATE.format(name=blob_name))
        if not args.no_runners:
            labels.append(RUNNER_LABEL.format(runner_type=runner_type))

        print(f"  [{config_key}] building... ", end="", flush=True)
        if not _bazel_build(bazel_config, labels):
            print("BUILD FAIL")
            total += len(args.targets) + (0 if args.no_runners else 1)
            continue
        print("OK")

        # Stage blobs.
        for blob_name in args.targets:
            total += 1
            label = BLOB_LABEL_TEMPLATE.format(name=blob_name)
            src = _find_bazel_output(label, ".so")
            dest = BLOB_DIR / os_name / arch_name / f"{blob_name}.so"

            tag = f"    {blob_name}.so → {os_name}/{arch_name}"
            if _stage_file(src, dest):
                print(f"{tag:<50s} OK")
                passed += 1
            else:
                print(f"{tag:<50s} NOT FOUND: {src}")

        # Stage runner.
        if not args.no_runners:
            total += 1
            runner_label = RUNNER_LABEL.format(runner_type=runner_type)
            # genrule outputs runner.bin
            src = _find_bazel_output(runner_label, ".bin")
            dest = RUNNER_DIR / runner_type / arch_name / "runner"

            tag = f"    runner → {runner_type}/{arch_name}"
            if _stage_file(src, dest, executable=True):
                print(f"{tag:<50s} OK")
                passed += 1
            else:
                print(f"{tag:<50s} NOT FOUND: {src}")

    print(f"\n{passed}/{total} staged")
    if passed < total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
