"""QEMU test runner orchestration.

Manages the lifecycle of running a PIC blob under QEMU user-static:
  1. Prepare a pre-extracted flat blob (code + config) in a temp file
  2. Invoke the appropriate C test runner under QEMU
  3. Capture and return stdout, stderr, exit code
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import logging
import platform
import selectors
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from picblobs._qemu import QEMU_BINARIES

if TYPE_CHECKING:
    from picblobs._extractor import BlobData

log = logging.getLogger(__name__)

# Fallback: Bazel build tree.
_BAZEL_RUNNER_SEARCH = [
    Path("bazel-bin/tests/runners"),
    Path("../bazel-bin/tests/runners"),
]


def _picblobs_cli_runner_dir() -> Path | None:
    """Return the on-disk path to the picblobs_cli bundled runners, or None.

    Companion package ``picblobs-cli`` ships the cross-compiled test
    runners under ``picblobs_cli/_runners``. When installed alongside
    picblobs it provides the primary source of runner binaries; if the
    package isn't importable we fall back to the Bazel build tree.
    """
    try:
        import importlib
        import importlib.resources

        mod = importlib.import_module("picblobs_cli")
    except ImportError:
        return None
    try:
        return Path(str(importlib.resources.files(mod) / "_runners"))
    except (AttributeError, ModuleNotFoundError, TypeError):
        return None


@dataclasses.dataclass(frozen=True)
class RunResult:
    """Result of running a blob under QEMU."""

    stdout: bytes
    stderr: bytes
    exit_code: int
    duration_s: float
    command: list[str]
    blob_file: str = ""


@dataclasses.dataclass(frozen=True)
class PairRunResult:
    """Result of running a server/client blob pair."""

    server_stdout: bytes
    server_stderr: bytes
    server_exit: int
    client_stdout: bytes
    client_stderr: bytes
    client_exit: int


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


def _find_embedded_runner(runner_type: str, arch: str) -> Path | None:
    """Return a bundled picblobs-cli runner if one is installed."""
    cli_dir = _picblobs_cli_runner_dir()
    if not cli_dir or not arch:
        return None
    embedded = cli_dir / runner_type / arch / "runner"
    if embedded.exists():
        return embedded
    return None


def _runner_candidates(base: Path, runner_type: str, arch: str) -> list[Path]:
    """Return candidate runner paths under one search root."""
    candidates: list[Path] = []
    if arch:
        candidates.extend(
            [
                base / runner_type / arch / "runner",
                base / runner_type / arch / "runner.bin",
            ]
        )
    candidates.extend(
        [
            base / runner_type / "runner.bin",
            base / runner_type / "runner",
        ]
    )
    return candidates


def _find_runner_in_paths(
    runner_type: str,
    arch: str,
    search_paths: list[Path],
) -> Path | None:
    """Return the first runner found in the supplied search roots."""
    for base in search_paths:
        for runner in _runner_candidates(base, runner_type, arch):
            if runner.exists():
                return runner
    return None


def find_runner(
    runner_type: str,
    arch: str = "",
    search_paths: list[Path] | None = None,
) -> Path:
    """Locate a compiled C test runner binary.

    Search order:
      1. ``picblobs-cli`` package: ``picblobs_cli/_runners/{runner_type}/{arch}/runner``
      2. Bazel build tree: ``bazel-bin/tests/runners/{runner_type}/{arch}/runner[.bin]``
      3. Caller-supplied ``search_paths``

    Args:
        runner_type: One of "linux", "freebsd", "windows".
        arch: Target architecture (e.g., "x86_64", "aarch64").
        search_paths: Override search directories.

    Raises:
        FileNotFoundError: If runner binary is not found. The error text
            mentions ``picblobs-cli`` so installation guidance is visible.
    """
    embedded = _find_embedded_runner(runner_type, arch)
    if embedded is not None:
        return embedded

    runner = _find_runner_in_paths(
        runner_type, arch, search_paths or _BAZEL_RUNNER_SEARCH
    )
    if runner is not None:
        return runner

    raise FileNotFoundError(
        f"Test runner not found for {runner_type}/{arch}. "
        f"Install picblobs-cli (pip install picblobs-cli) or run "
        f"tools/stage_blobs.py from a source checkout."
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
    blob_file = output_dir / _blob_filename(blob)

    data = bytearray(blob.code)

    # Append config at config_offset if provided.
    if config:
        if blob.config_offset > len(data):
            data.extend(b"\x00" * (blob.config_offset - len(data)))
        data[blob.config_offset : blob.config_offset + len(config)] = config

    blob_file.write_bytes(bytes(data))
    return blob_file


def _blob_filename(blob: BlobData) -> str:
    """Return the standard on-disk filename for a prepared blob."""
    return f"{blob.blob_type}_{blob.target_os}_{blob.target_arch}.bin"


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
    qemu = find_qemu(arch)
    return [str(qemu), str(runner_path), *args]


def build_blob_command(
    blob: BlobData,
    runner_path: Path,
    blob_file: Path,
    runner_type: str = "",
) -> list[str]:
    """Build the full execution command for a prepared blob file.

    This centralizes runner-specific command shaping, including the
    FreeBSD runner's optional ``text_end`` bound used to keep syscall
    patching scoped to executable code.
    """
    if not runner_type:
        runner_type = blob.target_os

    extra: list[str] = []
    if runner_type == "freebsd":
        t_end = _text_end(blob)
        if t_end > 0:
            extra = [f"{t_end:#x}"]

    return _build_command(runner_path, blob_file, blob.target_arch, extra)


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
    with contextlib.suppress(OSError):
        blob_file.parent.rmdir()


def wait_for_stdout_marker(
    proc: subprocess.Popen[bytes],
    marker: bytes,
    timeout: float,
) -> bytes:
    """Read from ``proc.stdout`` until ``marker`` appears or timeout expires.

    Returns all bytes consumed while waiting. Callers should prepend this to
    the eventual ``communicate()`` stdout if they need the full output.
    """
    if proc.stdout is None:
        return b""

    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as sel:
        sel.register(proc.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            events = sel.select(remaining)
            if not events:
                break
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            chunks.append(chunk)
            data = b"".join(chunks)
            if marker in data:
                return data
            if proc.poll() is not None:
                break
    return b"".join(chunks)


def reserve_tcp_port(host: str = "127.0.0.1") -> int:
    """Reserve an ephemeral TCP port number for a short-lived local test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _pair_commands(
    server_blob: BlobData,
    client_blob: BlobData,
    runner_path: Path,
    runner_type: str,
    server_config: bytes,
    client_config: bytes,
) -> tuple[Path, Path, list[str], list[str]]:
    """Prepare pair temp files and commands."""
    server_bin = prepare_blob(server_blob, config=server_config)
    client_bin = prepare_blob(client_blob, config=client_config)
    return (
        server_bin,
        client_bin,
        build_blob_command(server_blob, runner_path, server_bin, runner_type),
        build_blob_command(client_blob, runner_path, client_bin, runner_type),
    )


def _terminate_proc(proc: subprocess.Popen[bytes] | None) -> None:
    """Kill a running subprocess and wait for it to exit."""
    if proc is None or proc.poll() is not None:
        return
    proc.kill()
    proc.wait()


def _pair_run_attempt(
    server_cmd: list[str],
    client_cmd: list[str],
    ready_marker: bytes,
    startup_timeout: float,
    timeout: float,
) -> tuple[PairRunResult | None, str]:
    """Run one server/client attempt and return (result, error_message)."""
    server_proc = subprocess.Popen(
        server_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    client_proc: subprocess.Popen[bytes] | None = None
    try:
        server_prefix = wait_for_stdout_marker(
            server_proc, ready_marker, startup_timeout
        )
        if ready_marker not in server_prefix:
            server_proc.kill()
            server_stdout, server_stderr = server_proc.communicate()
            return None, (
                "server did not reach listening state: "
                f"stdout={(server_prefix + server_stdout)!r} "
                f"stderr={server_stderr!r}"
            )

        client_proc = subprocess.Popen(
            client_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            client_stdout, client_stderr = client_proc.communicate(timeout=timeout)
            server_stdout, server_stderr = server_proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_proc(server_proc)
            _terminate_proc(client_proc)
            return None, "pair timed out"
        else:
            result = PairRunResult(
                server_stdout=server_prefix + server_stdout,
                server_stderr=server_stderr,
                server_exit=server_proc.returncode,
                client_stdout=client_stdout,
                client_stderr=client_stderr,
                client_exit=client_proc.returncode,
            )
            if result.server_exit == 0 and result.client_exit == 0:
                return result, ""
            detail = (
                f"server exit={result.server_exit} stderr={result.server_stderr!r}; "
                f"client exit={result.client_exit} stderr={result.client_stderr!r}"
            )
            return None, detail
    except subprocess.TimeoutExpired:
        _terminate_proc(server_proc)
        _terminate_proc(client_proc)
        return None, "pair timed out"
    finally:
        _terminate_proc(server_proc)
        _terminate_proc(client_proc)


def run_blob_pair(
    server_blob: BlobData,
    client_blob: BlobData,
    runner_path: Path,
    runner_type: str = "",
    *,
    server_config: bytes = b"",
    client_config: bytes = b"",
    timeout: float = 30.0,
    ready_marker: bytes = b"[server] listening\n",
    startup_timeout: float = 5.0,
    attempts: int = 3,
    retry_delay: float = 0.25,
) -> PairRunResult:
    """Run a server/client blob pair with bounded retries for startup flakiness."""
    if not runner_type:
        runner_type = server_blob.target_os

    server_bin, client_bin, server_cmd, client_cmd = _pair_commands(
        server_blob,
        client_blob,
        runner_path,
        runner_type,
        server_config,
        client_config,
    )
    try:
        last_error = "pair did not run"
        for attempt in range(attempts):
            result, last_error = _pair_run_attempt(
                server_cmd,
                client_cmd,
                ready_marker,
                startup_timeout,
                timeout,
            )
            if result is not None:
                return result
            if attempt + 1 < attempts:
                time.sleep(retry_delay)
        raise RuntimeError(last_error)
    finally:
        _cleanup_blob_file(server_bin)
        _cleanup_blob_file(client_bin)


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

    if runner_path is None:
        runner_path = find_runner(runner_type, blob.target_arch)

    if dry_run:
        return _run_blob_dry(blob, config, runner_type, runner_path, debug)

    blob_file = prepare_blob(blob, config)

    if debug:
        _log_run_blob_start(blob, config, runner_path, blob_file)

    cmd = build_blob_command(blob, runner_path, blob_file, runner_type)

    if debug:
        log.debug("command:    %s", " ".join(cmd))

    try:
        return _execute_blob_command(cmd, blob_file, timeout, debug, stdin_data)
    except subprocess.TimeoutExpired:
        if not debug:
            _cleanup_blob_file(blob_file)
        raise
    finally:
        if not debug:
            _cleanup_blob_file(blob_file)


def _log_run_blob_start(
    blob: BlobData,
    config: bytes,
    runner_path: Path,
    blob_file: Path,
) -> None:
    """Emit debug logging before executing a blob."""
    log.debug("blob:       %s %s:%s", blob.blob_type, blob.target_os, blob.target_arch)
    log.debug("code size:  %d bytes", len(blob.code))
    log.debug("config:     %d bytes at offset %d", len(config), blob.config_offset)
    log.debug("runner:     %s", runner_path)
    log.debug("blob file:  %s", blob_file)


def _run_blob_dry(
    blob: BlobData,
    config: bytes,
    runner_type: str,
    runner_path: Path,
    debug: bool,
) -> RunResult:
    """Build a dry-run command without creating temp files."""
    blob_file = Path(_blob_filename(blob))
    cmd = build_blob_command(blob, runner_path, blob_file, runner_type)
    if debug:
        _log_run_blob_start(blob, config, runner_path, blob_file)
        log.debug("blob file:  %s (dry-run placeholder)", blob_file)
        log.debug("command:    %s", " ".join(cmd))
        log.debug("dry run — not executing")
    return RunResult(
        stdout=b"",
        stderr=b"",
        exit_code=0,
        duration_s=0.0,
        command=cmd,
        blob_file=str(blob_file),
    )


def _execute_blob_command(
    cmd: list[str],
    blob_file: Path,
    timeout: float,
    debug: bool,
    stdin_data: bytes,
) -> RunResult:
    """Execute a prepared blob command and return the captured result."""
    start = time.monotonic()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        check=False,
        input=stdin_data or None,
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


def run_so(*_args, **_kwargs) -> RunResult:
    """Fail explicitly: runtime .so extraction is not supported."""
    raise RuntimeError(
        "Runtime .so extraction is not supported. Generate sidecar artifacts "
        "with tools/stage_blobs.py or tools/extract_release.py, then load blobs "
        "through picblobs.get_blob()."
    )
