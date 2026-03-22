"""QEMU test runner orchestration.

Manages the lifecycle of running a PIC blob under QEMU user-static:
  1. Extract blob code from .so via picblobs._extractor
  2. Prepare a flat binary (code + config) in a temp file
  3. Invoke the appropriate C test runner under QEMU
  4. Capture and return stdout, stderr, exit code
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from picblobs._extractor import BlobData, extract

# QEMU user-static binary names per architecture.
QEMU_BINARIES: dict[str, str] = {
    "x86_64": "qemu-x86_64-static",
    "i686": "qemu-i386-static",
    "aarch64": "qemu-aarch64-static",
    "armv5_arm": "qemu-arm-static",
    "armv5_thumb": "qemu-arm-static",
    "mipsel32": "qemu-mipsel-static",
    "mipsbe32": "qemu-mips-static",
}

# Embedded runners inside the package.
_PACKAGE_RUNNER_DIR = Path(__file__).parent / "_runners"

# Fallback: Bazel build tree.
_BAZEL_RUNNER_SEARCH = [
    Path("bazel-bin/tests/runners"),
    Path("../bazel-bin/tests/runners"),
]


@dataclasses.dataclass(frozen=True)
class RunResult:
    """Result of running a blob under QEMU."""

    stdout: bytes
    stderr: bytes
    exit_code: int
    duration_s: float
    command: list[str]
    blob_file: str = ""


def find_qemu(arch: str) -> Path:
    """Locate the QEMU user-static binary for an architecture.

    Raises:
        FileNotFoundError: If QEMU binary is not found on PATH.
    """
    name = QEMU_BINARIES.get(arch)
    if name is None:
        raise ValueError(f"Unknown architecture: {arch}")

    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(
            f"{name} not found on PATH. Install qemu-user-static."
        )
    return Path(path)


def find_runner(
    runner_type: str,
    arch: str = "",
    search_paths: list[Path] | None = None,
) -> Path:
    """Locate a compiled C test runner binary.

    Search order:
      1. Embedded in package: picblobs/_runners/{runner_type}/{arch}/runner
      2. Bazel build tree: bazel-bin/tests/runners/{runner_type}/runner.bin

    Args:
        runner_type: One of "linux", "freebsd", "windows".
        arch: Target architecture (e.g., "x86_64", "aarch64").
        search_paths: Override search directories.

    Raises:
        FileNotFoundError: If runner binary is not found.
    """
    # 1. Check embedded runners (cross-compiled, per-arch).
    if arch:
        embedded = _PACKAGE_RUNNER_DIR / runner_type / arch / "runner"
        if embedded.exists():
            return embedded

    # 2. Fallback to Bazel build tree.
    paths = search_paths or _BAZEL_RUNNER_SEARCH
    for base in paths:
        # Try arch-specific first.
        if arch:
            runner = base / runner_type / arch / "runner"
            if runner.exists():
                return runner
            runner = base / runner_type / arch / "runner.bin"
            if runner.exists():
                return runner
        # Then generic (current config's output).
        runner = base / runner_type / "runner.bin"
        if runner.exists():
            return runner
        runner = base / runner_type / "runner"
        if runner.exists():
            return runner

    raise FileNotFoundError(
        f"Test runner not found for {runner_type}/{arch}. "
        f"Run: picblobs build"
    )


def prepare_blob(
    blob: BlobData,
    config: bytes = b"",
    output_dir: Path | None = None,
) -> Path:
    """Write blob code + config to a temp file.

    Args:
        blob: Extracted blob data.
        config: Serialized config struct to append at config_offset.
        output_dir: Directory for the temp file. Uses system temp if None.

    Returns:
        Path to the prepared blob binary file.
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="picblobs_"))

    output_dir.mkdir(parents=True, exist_ok=True)
    blob_file = output_dir / f"{blob.blob_type}_{blob.target_os}_{blob.target_arch}.bin"

    data = bytearray(blob.code)

    # Append config at config_offset if provided.
    if config:
        if blob.config_offset > len(data):
            data.extend(b"\x00" * (blob.config_offset - len(data)))
        data[blob.config_offset:blob.config_offset + len(config)] = config

    blob_file.write_bytes(bytes(data))
    return blob_file


def _build_command(
    runner_path: Path,
    blob_file: Path,
    arch: str,
) -> list[str]:
    """Build the QEMU + runner command line."""
    if arch == "x86_64":
        return [str(runner_path), str(blob_file)]
    else:
        qemu = find_qemu(arch)
        return [str(qemu), str(runner_path), str(blob_file)]


def run_blob(
    blob: BlobData,
    config: bytes = b"",
    runner_type: str = "",
    runner_path: Path | None = None,
    timeout: float = 30.0,
    debug: bool = False,
    dry_run: bool = False,
) -> RunResult:
    """Prepare and execute a blob under QEMU.

    Args:
        blob: Extracted blob data.
        config: Serialized config struct.
        runner_type: Test runner type ("linux", "freebsd", "windows").
            Defaults to blob.target_os.
        runner_path: Explicit path to the runner binary. Auto-discovered if None.
        timeout: Execution timeout in seconds.
        debug: Print verbose info (paths, command, timing). Keep temp files.
        dry_run: Build command but don't execute. Returns RunResult with command only.

    Returns:
        RunResult with stdout, stderr, exit code, and duration.

    Raises:
        FileNotFoundError: If QEMU or runner binary not found.
        subprocess.TimeoutExpired: If execution exceeds timeout.
    """
    if not runner_type:
        runner_type = blob.target_os

    # Locate runner.
    if runner_path is None:
        runner_path = find_runner(runner_type, blob.target_arch)

    # Prepare the blob binary.
    blob_file = prepare_blob(blob, config)

    if debug:
        print(f"[debug] blob:       {blob.blob_type} {blob.target_os}:{blob.target_arch}", file=sys.stderr)
        print(f"[debug] code size:  {len(blob.code)} bytes", file=sys.stderr)
        print(f"[debug] config:     {len(config)} bytes at offset {blob.config_offset}", file=sys.stderr)
        print(f"[debug] runner:     {runner_path}", file=sys.stderr)
        print(f"[debug] blob file:  {blob_file}", file=sys.stderr)

    # Build the command.
    cmd = _build_command(runner_path, blob_file, blob.target_arch)

    if debug:
        print(f"[debug] command:    {' '.join(cmd)}", file=sys.stderr)

    if dry_run:
        if debug:
            print(f"[debug] dry run — not executing", file=sys.stderr)
        return RunResult(
            stdout=b"",
            stderr=b"",
            exit_code=0,
            duration_s=0.0,
            command=cmd,
            blob_file=str(blob_file),
        )

    try:
        start = time.monotonic()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
        )
        duration = time.monotonic() - start

        if debug:
            print(f"[debug] exit code:  {proc.returncode}", file=sys.stderr)
            print(f"[debug] duration:   {duration:.3f}s", file=sys.stderr)
            print(f"[debug] temp dir:   {blob_file.parent} (preserved)", file=sys.stderr)

        return RunResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            duration_s=duration,
            command=cmd,
            blob_file=str(blob_file),
        )
    finally:
        if not debug:
            blob_file.unlink(missing_ok=True)
            try:
                blob_file.parent.rmdir()
            except OSError:
                pass


def run_so(
    so_path: str | Path,
    config: bytes = b"",
    runner_type: str = "",
    runner_path: Path | None = None,
    timeout: float = 30.0,
    debug: bool = False,
    dry_run: bool = False,
) -> RunResult:
    """Extract a .so and run it in one call.

    Convenience for the --so development workflow.
    """
    blob = extract(so_path)
    if not runner_type:
        runner_type = blob.target_os or "linux"
    return run_blob(
        blob,
        config=config,
        runner_type=runner_type,
        runner_path=runner_path,
        timeout=timeout,
        debug=debug,
        dry_run=dry_run,
    )
