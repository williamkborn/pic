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
from registry import BLOB_TYPES, platform_configs

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
DEBUG_BLOB_DIR = PROJECT_ROOT / "debug"


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


def bazel_build(configs: list[str], labels: list[str]) -> bool:
    """Run bazel build for configs+labels. Returns True on success."""
    cmd = ["bazel", "build"] + [f"--config={c}" for c in configs] + labels
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


# Substrings from `file -b` output for architecture validation.
_ELF_MACHINES = {
    "x86_64": "x86-64",
    "i686": "Intel",  # matches "Intel 80386" and "Intel i386"
    "aarch64": "aarch64",
    "armv5_arm": "ARM",
    "armv5_thumb": "ARM",
    "armv7_thumb": "ARM",
    "s390x": "S/390",
    "mipsel32": "MIPS",
    "mipsbe32": "MIPS",
}


def verify_elf_arch(so_path: Path, expected_arch: str) -> bool:
    """Verify a staged .so has the expected ELF machine type.

    Catches the bug where bazel-bin symlink points to wrong-platform output.
    """
    expected = _ELF_MACHINES.get(expected_arch)
    if expected is None:
        return True  # unknown arch, skip check
    try:
        result = subprocess.run(
            ["file", "-b", str(so_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return expected in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True  # can't check, don't block


def find_bazel_output(label: str, extension: str) -> Path:
    """Convert a Bazel label to its output path in bazel-bin/."""
    pkg, name = label.lstrip("/").split(":")
    return PROJECT_ROOT / "bazel-bin" / pkg / f"{name}{extension}"


def build_and_stage(
    targets: list[str],
    configs: list[str],
    no_runners: bool = False,
    debug: bool = False,
) -> tuple[int, int]:
    """Build and stage blobs+runners. Returns (passed, total).

    If debug=True, builds with _debug configs and stages to debug/ instead
    of the Python package tree. Runners are not built in debug mode.
    """
    total = 0
    passed = 0
    output_dir = DEBUG_BLOB_DIR if debug else BLOB_DIR

    for config_key in configs:
        if config_key not in PLATFORM_CONFIGS:
            log.error("Unknown config: %s", config_key)
            continue

        bazel_config, runner_type = PLATFORM_CONFIGS[config_key]
        os_name, arch_name = config_key.split(":")

        bazel_configs = [bazel_config]
        if debug:
            bazel_configs.append("debug")

        # Filter targets to those compatible with this OS.
        # Blobs with an OS suffix (e.g. hello_windows) only build for that OS.
        # Blobs without a suffix are unix-only (use raw syscalls, not Win API).
        os_targets = []
        for blob_name in targets:
            parts = blob_name.rsplit("_", 1)
            if len(parts) == 2 and parts[1] in ("linux", "freebsd", "windows"):
                # Explicit OS suffix — must match.
                if parts[1] != os_name:
                    continue
            else:
                # No OS suffix — unix blob, skip for Windows.
                if os_name == "windows":
                    continue
            os_targets.append(blob_name)

        blob_labels = []
        for blob_name in os_targets:
            blob_labels.append(BLOB_LABEL_TEMPLATE.format(name=blob_name))

        want_runner = not no_runners and not debug
        runner_label = (
            RUNNER_LABEL.format(runner_type=runner_type) if want_runner else ""
        )

        if not blob_labels and not runner_label:
            continue

        mode = "debug" if debug else "release"

        # Build blobs with the target platform config.
        if blob_labels:
            log.info("  [%s] (%s) building blobs... ", config_key, mode)
            if not bazel_build(bazel_configs, blob_labels):
                log.error("  [%s] BLOB BUILD FAIL", config_key)
                total += len(os_targets)
                blob_labels = []  # skip staging
            else:
                log.info("  [%s] blobs OK", config_key)

        # Stage blobs immediately after building them, BEFORE the runner
        # build changes the bazel-bin symlink to a different config.
        for blob_name in os_targets:
            if not blob_labels:
                break  # build failed, skip staging
            total += 1
            label = BLOB_LABEL_TEMPLATE.format(name=blob_name)
            src = find_bazel_output(label, ".so")
            # Use staged_name from registry if set (e.g. alloc_jump_windows
            # stages as alloc_jump.so), otherwise use the blob name as-is.
            bt = BLOB_TYPES.get(blob_name)
            staged_name = (bt.staged_name if bt and bt.staged_name else blob_name)
            dest = output_dir / os_name / arch_name / f"{staged_name}.so"

            tag = f"    {staged_name}.so -> {os_name}/{arch_name}"
            if stage_file(src, dest):
                if not verify_elf_arch(dest, arch_name):
                    log.error(
                        "%-50s ARCH MISMATCH (expected %s)", tag, arch_name
                    )
                else:
                    log.info("%-50s OK", tag)
                    passed += 1
            else:
                log.error("%-50s NOT FOUND: %s", tag, src)

        # Build runner AFTER staging blobs. The Windows/FreeBSD runners
        # are Linux binaries (mock environments), built with a Linux config
        # which changes the bazel-bin symlink.
        if runner_label:
            if os_name in ("windows", "freebsd"):
                runner_bazel_config = f"linux_{arch_name}"
                runner_configs = [runner_bazel_config]
            else:
                runner_configs = list(bazel_configs)
            log.info("  [%s] (%s) building runner... ", config_key, mode)
            if not bazel_build(runner_configs, [runner_label]):
                log.error("  [%s] RUNNER BUILD FAIL", config_key)
                runner_label = ""  # skip staging
            else:
                log.info("  [%s] runner OK", config_key)

        if runner_label:
            total += 1
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
    # Default to Linux + Windows configs. FreeBSD runners are not yet buildable.
    _default_configs = [
        k
        for k in PLATFORM_CONFIGS
        if k.startswith("linux:") or k.startswith("windows:")
    ]
    parser.add_argument(
        "--configs",
        nargs="*",
        default=_default_configs,
        help="Platform configs as os:arch (default: linux + windows)",
    )
    parser.add_argument(
        "--no-runners",
        action="store_true",
        help="Skip building/staging test runners",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build debug variants (with -g and PIC_LOG) staged to debug/",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if args.targets is None:
        args.targets = discover_blob_targets()

    passed, total = build_and_stage(
        args.targets, args.configs, args.no_runners, args.debug
    )

    log.info("%d/%d staged", passed, total)
    if passed < total:
        return 1

    # Auto-regenerate pre-extracted release blobs so get_blob() sees
    # the freshly-staged .so files immediately. Without this step,
    # get_blob() reads stale .bin files from blobs/ and changes appear
    # to have no effect — a common source of debugging confusion.
    if not args.debug and passed > 0:
        log.info("  extracting release blobs...")
        from extract_release import extract_release

        so_dir = BLOB_DIR
        out_dir = PROJECT_ROOT / "python" / "picblobs"
        extracted, errors = extract_release(so_dir, out_dir)
        log.info("  %d blobs extracted (%d errors)", extracted, errors)
        if errors:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
