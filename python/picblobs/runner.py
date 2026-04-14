"""QEMU test runner orchestration.

Manages the lifecycle of running a PIC blob under QEMU user-static:
  1. Extract blob code from .so via picblobs._extractor
  2. Prepare a flat binary (code + config) in a temp file
  3. Invoke the appropriate C test runner under QEMU
  4. Capture and return stdout, stderr, exit code
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

from picblobs._extractor import BlobData, extract
from picblobs._qemu import QEMU_BINARIES

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
        raise FileNotFoundError(f"{name} not found on PATH. Install qemu-user-static.")
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
        f"Test runner not found for {runner_type}/{arch}. Run: picblobs build"
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
        data[blob.config_offset : blob.config_offset + len(config)] = config

    blob_file.write_bytes(bytes(data))
    return blob_file


# Architectures whose PIC blobs write to the GOT at runtime.
# QEMU's self-modifying-code detection for these targets crashes under
# Rosetta 2 (Apple Silicon Docker Desktop) because the GOT lives on the
# same page as executable code.
_QEMU_MIPS_ARCHES: frozenset[str] = frozenset({"mipsel32", "mipsbe32"})


@functools.cache
def is_rosetta() -> bool:
    """Detect Rosetta 2 x86_64 emulation (e.g. Docker Desktop on Apple Silicon).

    Under Rosetta, /proc/cpuinfo reports ``vendor_id : VirtualApple``,
    whereas real x86_64 hardware reports GenuineIntel or AuthenticAMD.
    """
    if platform.machine() != "x86_64":
        return False
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
    except (FileNotFoundError, OSError):
        return False
    return "VirtualApple" in cpuinfo


def is_arch_skip_rosetta(arch: str) -> bool:
    """Return True if *arch* should be skipped under Rosetta.

    QEMU MIPS user-static crashes when running PIC blobs that perform GOT
    self-relocation on the same page as executable code.  This is a known
    QEMU/Rosetta incompatibility — the blobs work on native x86_64 hosts.
    """
    return arch in _QEMU_MIPS_ARCHES and is_rosetta()


def _is_native_arch(arch: str) -> bool:
    """Check if the given blob architecture can run natively on this host."""
    host = platform.machine()
    # Map our arch names to platform.machine() values.
    # Only 64-bit arches get native execution; 32-bit compat (e.g., i686
    # on x86_64) requires the runner to be compiled for that arch which
    # still needs the cross-compiled runner binary, so use QEMU.
    native_map: dict[str, str] = {
        "x86_64": "x86_64",
        "aarch64": "aarch64",
    }
    return native_map.get(arch, "") == host


def _build_command(
    runner_path: Path,
    blob_file: Path,
    arch: str,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build the QEMU + runner command line."""
    args = [str(blob_file), *(extra_args or [])]
    if _is_native_arch(arch):
        return [str(runner_path), *args]
    else:
        qemu = find_qemu(arch)
        return [str(qemu), str(runner_path), *args]


def _text_end(blob: BlobData) -> int:
    """Return the largest offset covered by a .text* section, or 0 if none."""
    end = 0
    for name, (off, size) in blob.sections.items():
        if name.startswith(".text"):
            end = max(end, off + size)
    return end


def _cleanup_blob_file(blob_file: Path) -> None:
    """Remove a temp blob file and its parent directory."""
    blob_file.unlink(missing_ok=True)
    try:
        blob_file.parent.rmdir()
    except OSError:
        pass


def run_blob(
    blob: BlobData,
    config: bytes = b"",
    runner_type: str = "",
    runner_path: Path | None = None,
    timeout: float = 30.0,
    debug: bool = False,
    dry_run: bool = False,
    stdin_data: bytes = b"",
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
        stdin_data: Bytes to feed to the blob's stdin — used by stager_fd
            tests so the blob can read a length-prefixed payload from fd 0.

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
        log.debug(
            "blob:       %s %s:%s", blob.blob_type, blob.target_os, blob.target_arch
        )
        log.debug("code size:  %d bytes", len(blob.code))
        log.debug("config:     %d bytes at offset %d", len(config), blob.config_offset)
        log.debug("runner:     %s", runner_path)
        log.debug("blob file:  %s", blob_file)

    # Build the command. FreeBSD runner accepts an optional text_end
    # bound (hex) to scope syscall-number patching to the code region.
    extra: list[str] = []
    if runner_type == "freebsd":
        t_end = _text_end(blob)
        if t_end > 0:
            extra = [f"{t_end:#x}"]
    cmd = _build_command(runner_path, blob_file, blob.target_arch, extra)

    if debug:
        log.debug("command:    %s", " ".join(cmd))

    if dry_run:
        if debug:
            log.debug("dry run — not executing")
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
            input=stdin_data if stdin_data else None,
            timeout=timeout,
        )
        duration = time.monotonic() - start

        if debug:
            log.debug("exit code:  %d", proc.returncode)
            log.debug("duration:   %.3fs", duration)
            log.debug("temp dir:   %s (preserved)", blob_file.parent)

        return RunResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            duration_s=duration,
            command=cmd,
            blob_file=str(blob_file),
        )
    except subprocess.TimeoutExpired:
        if not debug:
            _cleanup_blob_file(blob_file)
        raise
    finally:
        if not debug:
            _cleanup_blob_file(blob_file)


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
    if not blob.target_arch:
        raise ValueError(
            f"Cannot determine architecture from {so_path}. "
            "Pass target info via extract() or use run_blob() directly."
        )
    return run_blob(
        blob,
        config=config,
        runner_type=runner_type,
        runner_path=runner_path,
        timeout=timeout,
        debug=debug,
        dry_run=dry_run,
    )
