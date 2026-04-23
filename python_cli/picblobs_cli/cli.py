"""picblobs-cli click command tree.

Implements REQ-020: ``run``, ``verify``, ``build``, ``list-runners``,
``info``. Each command delegates to ``picblobs`` for data access and to
``picblobs.runner`` for QEMU orchestration.
"""

from __future__ import annotations

import os as _os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import click

import picblobs
from picblobs import (
    Arch,
    Blob,
    BlobType,
    OS,
    ValidationError,
)
from picblobs.runner import find_runner, run_blob
from picblobs_cli import __version__ as CLI_VERSION
from picblobs_cli import runners_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_target(target: str) -> tuple[str, str]:
    if ":" not in target:
        raise click.BadParameter(
            f"Invalid target {target!r} (expected os:arch, e.g. linux:x86_64)"
        )
    os_name, arch = target.split(":", 1)
    # Validate against the enums but keep the string form so downstream
    # code (picblobs.get_blob, run_blob) sees canonical lowercase strings.
    OS.parse(os_name)
    Arch.parse(arch)
    return os_name.lower(), arch.lower()


def _fail(message: str) -> None:
    click.echo(f"error: {message}", err=True)
    sys.exit(1)


def _length_prefixed(payload: bytes) -> bytes:
    return struct.pack("<I", len(payload)) + payload


def _iter_runner_binaries(
    root: Path,
    os_filter: str | None,
    arch_filter: str | None,
):
    """Yield bundled runner tuples as (runner_type, arch, runner_path)."""
    for runner_type_dir in sorted(root.iterdir()):
        if not runner_type_dir.is_dir():
            continue
        if os_filter and runner_type_dir.name != os_filter:
            continue
        for arch_dir in sorted(runner_type_dir.iterdir()):
            if not arch_dir.is_dir():
                continue
            if arch_filter and arch_dir.name != arch_filter:
                continue
            runner = arch_dir / "runner"
            if runner.exists():
                yield runner_type_dir.name, arch_dir.name, runner


def _check_allowed_options(
    blob: BlobType,
    allowed: set[str],
    provided: dict[str, bool],
) -> None:
    """Fail if unsupported options were supplied for a blob type."""
    bad = [name for name, supplied in provided.items() if supplied and name not in allowed]
    if bad:
        _fail(
            f"{blob.value}: options {sorted(bad)} are not valid for this "
            f"blob type (allowed: {sorted(allowed)})"
        )


def _provided_build_options(
    payload_file: Path | None,
    address: str | None,
    port: int | None,
    fd: int | None,
    stage_path: str | None,
    offset: int,
    size: int | None,
    pe_file: Path | None,
    call_dll_main: bool,
    elf_file: Path | None,
    argv: tuple[str, ...],
    envp: tuple[str, ...],
) -> dict[str, bool]:
    """Return a normalized map of supplied build options."""
    return {
        "payload": payload_file is not None,
        "address": address is not None,
        "port": port is not None,
        "fd": fd is not None,
        "path": stage_path is not None,
        "offset": offset != 0,
        "size": size is not None,
        "pe": pe_file is not None,
        "call-dll-main": call_dll_main,
        "elf": elf_file is not None,
        "argv": len(argv) > 0,
        "envp": len(envp) > 0,
    }


def _build_blob_bytes(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    payload_file: Path | None,
    address: str | None,
    port: int | None,
    fd: int | None,
    stage_path: str | None,
    offset: int,
    size: int | None,
    pe_file: Path | None,
    call_dll_main: bool,
    elf_file: Path | None,
    argv: tuple[str, ...],
    envp: tuple[str, ...],
) -> bytes:
    """Build bytes for one blob type from click CLI options."""
    build_fn = _BUILDERS.get(blob)
    if build_fn is None:
        _fail(f"{blob.value}: not buildable via this CLI")
    return build_fn(
        base,
        blob,
        provided,
        payload_file,
        address,
        port,
        fd,
        stage_path,
        offset,
        size,
        pe_file,
        call_dll_main,
        elf_file,
        argv,
        envp,
    )


def _build_hello(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    *_args,
) -> bytes:
    _check_allowed_options(blob, set(), provided)
    return base.hello().build()


def _build_hello_windows(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    *_args,
) -> bytes:
    _check_allowed_options(blob, set(), provided)
    return base.hello_windows().build()


def _build_alloc_jump(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    payload_file: Path | None,
    *_args,
) -> bytes:
    _check_allowed_options(blob, {"payload"}, provided)
    if payload_file is None:
        _fail("alloc_jump requires --payload FILE")
    return base.alloc_jump().payload(payload_file.read_bytes()).build()


def _build_stager_tcp(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    _payload_file: Path | None,
    address: str | None,
    port: int | None,
    *_args,
) -> bytes:
    _check_allowed_options(blob, {"address", "port"}, provided)
    if address is None or port is None:
        _fail("stager_tcp requires --address and --port")
    return base.stager_tcp().address(address).port(port).build()


def _build_stager_fd(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    _payload_file: Path | None,
    _address: str | None,
    _port: int | None,
    fd: int | None,
    *_args,
) -> bytes:
    _check_allowed_options(blob, {"fd"}, provided)
    return base.stager_fd().fd(fd if fd is not None else 0).build()


def _build_stager_pipe(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    _payload_file: Path | None,
    _address: str | None,
    _port: int | None,
    _fd: int | None,
    stage_path: str | None,
    *_args,
) -> bytes:
    _check_allowed_options(blob, {"path"}, provided)
    if stage_path is None:
        _fail("stager_pipe requires --path")
    return base.stager_pipe().path(stage_path).build()


def _build_stager_mmap(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    _payload_file: Path | None,
    _address: str | None,
    _port: int | None,
    _fd: int | None,
    stage_path: str | None,
    offset: int,
    size: int | None,
    *_args,
) -> bytes:
    _check_allowed_options(blob, {"path", "offset", "size"}, provided)
    if stage_path is None or size is None:
        _fail("stager_mmap requires --path and --size")
    builder = base.stager_mmap().path(stage_path).size(size)
    if offset:
        builder = builder.offset(offset)
    return builder.build()


def _build_reflective_pe(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    _payload_file: Path | None,
    _address: str | None,
    _port: int | None,
    _fd: int | None,
    _stage_path: str | None,
    _offset: int,
    _size: int | None,
    pe_file: Path | None,
    call_dll_main: bool,
    *_args,
) -> bytes:
    _check_allowed_options(blob, {"pe", "call-dll-main"}, provided)
    if pe_file is None:
        _fail("reflective_pe requires --pe FILE")
    builder = base.reflective_pe().pe(pe_file.read_bytes())
    if call_dll_main:
        builder = builder.call_dll_main(True)
    return builder.build()


def _build_ul_exec(
    base: Blob,
    blob: BlobType,
    provided: dict[str, bool],
    _payload_file: Path | None,
    _address: str | None,
    _port: int | None,
    _fd: int | None,
    _stage_path: str | None,
    _offset: int,
    _size: int | None,
    _pe_file: Path | None,
    _call_dll_main: bool,
    elf_file: Path | None,
    argv: tuple[str, ...],
    envp: tuple[str, ...],
) -> bytes:
    _check_allowed_options(blob, {"elf", "argv", "envp"}, provided)
    if elf_file is None:
        _fail("ul_exec requires --elf FILE")
    builder = base.ul_exec().elf(elf_file.read_bytes())
    if argv:
        builder = builder.argv(list(argv))
    if envp:
        builder = builder.envp(list(envp))
    return builder.build()


_BUILDERS = {
    BlobType.HELLO: _build_hello,
    BlobType.HELLO_WINDOWS: _build_hello_windows,
    BlobType.ALLOC_JUMP: _build_alloc_jump,
    BlobType.STAGER_TCP: _build_stager_tcp,
    BlobType.STAGER_FD: _build_stager_fd,
    BlobType.STAGER_PIPE: _build_stager_pipe,
    BlobType.STAGER_MMAP: _build_stager_mmap,
    BlobType.REFLECTIVE_PE: _build_reflective_pe,
    BlobType.UL_EXEC: _build_ul_exec,
}


# ---------------------------------------------------------------------------
# Root command
# ---------------------------------------------------------------------------


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=CLI_VERSION, prog_name="picblobs-cli")
def main() -> None:
    """picblobs-cli — build, run, and verify PIC blobs under QEMU."""


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


@main.command()
def info() -> None:
    """Print versions, runner bundle path, and QEMU availability."""
    click.echo(f"picblobs:     {picblobs.__version__}")
    click.echo(f"picblobs-cli: {CLI_VERSION}")
    click.echo(f"runner bundle: {runners_dir()}")

    # QEMU detection.
    from picblobs._qemu import QEMU_BINARIES

    found: list[str] = []
    missing: list[str] = []
    for arch, binary in sorted(QEMU_BINARIES.items()):
        path = shutil.which(binary)
        (found if path else missing).append(arch)
    click.echo(f"qemu found:    {', '.join(found) or '<none>'}")
    if missing:
        click.echo(f"qemu missing:  {', '.join(missing)}")

    click.echo("")
    click.echo("Targets:")
    for t in picblobs.targets():
        types = picblobs.blob_types(t.os, t.arch)
        click.echo(f"  {t}  ({len(types)} blob types)")


# ---------------------------------------------------------------------------
# list-runners
# ---------------------------------------------------------------------------


@main.command("list-runners")
@click.option("--os", "os_filter", help="Filter to a single runner OS")
@click.option("--arch", "arch_filter", help="Filter to a single arch")
def list_runners(os_filter: str | None, arch_filter: str | None) -> None:
    """List every bundled (runner_type, arch) runner binary."""
    root = runners_dir()
    if not root.exists():
        _fail(
            f"runner bundle not found at {root}. "
            f"Run tools/stage_blobs.py first."
        )

    fmt = "{:<10s} {:<15s} {}"
    click.echo(fmt.format("RUNNER", "ARCH", "PATH"))
    click.echo(fmt.format("-" * 10, "-" * 15, "-" * 40))

    found = False
    for runner_type, arch, runner in _iter_runner_binaries(root, os_filter, arch_filter):
        found = True
        click.echo(fmt.format(runner_type, arch, str(runner)))

    if not found:
        _fail("no runners found (check --os / --arch filters)")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


@main.command()
@click.argument("blob_type")
@click.argument("target")
@click.option("-o", "--output", "output_path", required=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Output file (written as raw bytes)")
@click.option("--payload", "payload_file",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Payload bytes (alloc_jump)")
@click.option("--address", help="IPv4 address (stager_tcp)")
@click.option("--port", type=int, help="TCP port (stager_tcp)")
@click.option("--fd", type=int, help="File descriptor (stager_fd)")
@click.option("--path", "stage_path", help="FIFO or file path (stager_pipe, stager_mmap)")
@click.option("--offset", type=int, default=0, help="File offset (stager_mmap)")
@click.option("--size", type=int, help="Byte count to map (stager_mmap)")
@click.option("--pe", "pe_file",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="PE image (reflective_pe)")
@click.option("--call-dll-main", is_flag=True, help="Call DllMain (reflective_pe)")
@click.option("--elf", "elf_file",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="ELF image (ul_exec)")
@click.option("--argv", multiple=True, help="argv entry (ul_exec, repeatable)")
@click.option("--envp", multiple=True, help="envp entry (ul_exec, repeatable)")
def build(
    blob_type: str,
    target: str,
    output_path: Path,
    payload_file: Path | None,
    address: str | None,
    port: int | None,
    fd: int | None,
    stage_path: str | None,
    offset: int,
    size: int | None,
    pe_file: Path | None,
    call_dll_main: bool,
    elf_file: Path | None,
    argv: tuple[str, ...],
    envp: tuple[str, ...],
) -> None:
    """Assemble a blob via the builder API and write it to OUTPUT."""
    os_name, arch = _parse_target(target)
    try:
        blob = BlobType.parse(blob_type)
    except ValidationError as e:
        _fail(str(e))

    provided = _provided_build_options(
        payload_file,
        address,
        port,
        fd,
        stage_path,
        offset,
        size,
        pe_file,
        call_dll_main,
        elf_file,
        argv,
        envp,
    )

    try:
        out = _build_blob_bytes(
            Blob(os_name, arch),
            blob,
            provided,
            payload_file,
            address,
            port,
            fd,
            stage_path,
            offset,
            size,
            pe_file,
            call_dll_main,
            elf_file,
            argv,
            envp,
        )
    except ValidationError as e:
        _fail(str(e))

    output_path.write_bytes(out)
    click.echo(f"wrote {len(out)} bytes to {output_path}")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _run_file(
    blob_file: Path,
    os_name: str,
    arch: str,
    stdin_data: bytes,
    timeout: float,
    debug: bool,
) -> None:
    """Execute an already-assembled blob file under the correct runner.

    Unlike the registry path, we don't construct a ``BlobData`` or
    append a config — the file is assumed to be a complete blob image
    and is passed straight to the runner binary.
    """
    from picblobs.runner import _build_command

    try:
        runner_path = find_runner(os_name, arch)
    except FileNotFoundError as e:
        _fail(str(e))

    cmd = _build_command(runner_path, blob_file, arch)

    if debug:
        click.echo(f"runner:    {runner_path}", err=True)
        click.echo(f"blob file: {blob_file} ({blob_file.stat().st_size} B)", err=True)
        click.echo(f"command:   {' '.join(cmd)}", err=True)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            input=stdin_data if stdin_data else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _fail(f"blob timed out after {timeout}s")

    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(result.returncode)


def _parse_run_mode(
    positional: tuple[str, ...],
    blob_file: Path | None,
) -> tuple[str | None, str]:
    """Return (blob_type, target) for file or registry run mode."""
    if blob_file is not None:
        if len(positional) != 1:
            _fail(
                "with --file, supply exactly one positional: TARGET "
                "(got: " + " ".join(repr(p) for p in positional) + ")"
            )
        return None, positional[0]
    if len(positional) != 2:
        _fail(
            "registry mode expects two positionals: "
            "picblobs-cli run <blob_type> <target>"
        )
    return positional[0], positional[1]


def _registry_run_config(
    config_hex: str | None,
    payload_file: Path | None,
) -> bytes:
    """Return registry-mode config bytes."""
    if config_hex:
        try:
            return bytes.fromhex(config_hex)
        except ValueError as e:
            _fail(f"invalid --config-hex: {e}")
    if payload_file:
        return payload_file.read_bytes()
    return b""


def _emit_run_result(stdout: bytes, stderr: bytes, exit_code: int) -> None:
    """Write subprocess output to stdio and exit with the given code."""
    sys.stdout.buffer.write(stdout)
    sys.stderr.buffer.write(stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(exit_code)


def _run_registry_blob(
    blob_type: str,
    os_name: str,
    arch: str,
    config: bytes,
    timeout: float,
    debug: bool,
    stdin_data: bytes,
) -> None:
    """Run a staged blob looked up from the package registry."""
    try:
        blob_data = picblobs.get_blob(blob_type, os_name, arch)
    except FileNotFoundError as e:
        _fail(str(e))

    try:
        result = run_blob(
            blob_data,
            config=config,
            timeout=timeout,
            debug=debug,
            stdin_data=stdin_data,
        )
    except FileNotFoundError as e:
        _fail(str(e))
    except subprocess.TimeoutExpired:
        _fail(f"blob timed out after {timeout}s")

    _emit_run_result(result.stdout, result.stderr, result.exit_code)


@main.command()
@click.argument("positional", nargs=-1, required=True)
@click.option("-f", "--file", "blob_file",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Run an already-assembled blob file instead of "
                   "looking up by blob type. Bypasses the config / "
                   "extraction pipeline — the file is handed to the "
                   "runner as-is.")
@click.option("--config-hex", help="Config bytes as hex (registry mode only)")
@click.option("--payload", "payload_file",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Read config from a file (registry mode only)")
@click.option("--stdin", "stdin_file",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Pipe file contents to the blob's stdin")
@click.option("--timeout", type=float, default=30.0, show_default=True)
@click.option("--debug", is_flag=True, help="Verbose output, keep temp files")
def run(
    positional: tuple[str, ...],
    blob_file: Path | None,
    config_hex: str | None,
    payload_file: Path | None,
    stdin_file: Path | None,
    timeout: float,
    debug: bool,
) -> None:
    """Run a PIC blob under the bundled runner and QEMU.

    Two modes:

    \b
      picblobs-cli run <blob_type> <target>      # registry lookup
      picblobs-cli run --file FILE <target>      # already-assembled blob

    File mode is what you want after ``picblobs-cli build ... -o out.bin``
    or any other flow that produces a complete (code+config) blob.
    """
    blob_type, target = _parse_run_mode(positional, blob_file)
    os_name, arch = _parse_target(target)
    stdin_data = stdin_file.read_bytes() if stdin_file else b""

    if blob_file is not None:
        if config_hex or payload_file:
            _fail(
                "--config-hex / --payload have no effect with --file; "
                "assemble the blob first via 'picblobs-cli build ... -o FILE'"
            )
        _run_file(blob_file, os_name, arch, stdin_data, timeout, debug)
        return

    assert blob_type is not None
    _run_registry_blob(
        blob_type,
        os_name,
        arch,
        _registry_run_config(config_hex, payload_file),
        timeout,
        debug,
        stdin_data,
    )


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def _verify_one(blob_type: str, os_name: str, arch: str, timeout: float):
    """Dispatcher that mirrors the fixture logic from the legacy CLI."""
    blob = picblobs.get_blob(blob_type, os_name, arch)

    if blob_type == "stager_tcp":
        return _verify_stager_tcp(os_name, arch, timeout)
    if blob_type == "stager_fd":
        return _verify_stager_fd(os_name, arch, timeout)
    if blob_type == "stager_pipe":
        return _verify_stager_pipe(os_name, arch, timeout)
    if blob_type == "stager_mmap":
        return _verify_stager_mmap(os_name, arch, timeout)
    if blob_type == "alloc_jump":
        return _verify_alloc_jump(os_name, arch, timeout)
    if blob_type == "reflective_pe":
        return _verify_reflective_pe(os_name, arch, timeout)
    if blob_type == "ul_exec":
        return _verify_ul_exec(os_name, arch, timeout)

    return run_blob(blob, runner_type=os_name, timeout=timeout)


class _VerifySummary:
    """Mutable counters and output helpers for the click verify command."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors: list[str] = []

    def ok(self, label: str, detail: str) -> None:
        click.echo(f"  {label:<20}  OK   {detail}")
        self.passed += 1

    def skip(self, label: str, reason: str) -> None:
        click.echo(f"  {label:<20}  SKIP ({reason})")
        self.skipped += 1

    def fail(self, blob_type: str, label: str, detail: str) -> None:
        click.echo(f"  {label:<20}  {detail}", err=True)
        self.failed += 1
        self.errors.append(f"{blob_type}/{label}")

    def emit(self) -> None:
        total = self.passed + self.failed + self.skipped
        click.echo("")
        parts = [f"{self.passed}/{total} passed"]
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if self.errors:
            parts.append(f"failed: {', '.join(self.errors)}")
        click.echo("  ".join(parts))


def _filter_verify_combos(
    combos: list[tuple[str, str, str]],
    os_filter: tuple[str, ...],
    arch_filter: tuple[str, ...],
    type_filter: tuple[str, ...],
) -> list[tuple[str, str, str]]:
    """Apply click verify filters to staged blob triples."""
    filters = (
        (set(os_filter) if os_filter else None, 1),
        (set(arch_filter) if arch_filter else None, 2),
        (set(type_filter) if type_filter else None, 0),
    )
    for allowed, index in filters:
        if allowed:
            combos = [entry for entry in combos if entry[index] in allowed]
    combos = [
        entry
        for entry in combos
        if _is_verify_target_supported(entry[0], entry[1], entry[2])
    ]
    return combos


def _is_verify_target_supported(blob_type: str, os_name: str, arch: str) -> bool:
    if os_name != "freebsd":
        return True
    if arch != "x86_64":
        return False
    return blob_type != "ul_exec"


def _group_verify_combos(
    combos: list[tuple[str, str, str]],
) -> dict[tuple[str, str], list[str]]:
    """Group verify triples by (os, blob_type)."""
    groups: dict[tuple[str, str], list[str]] = {}
    for bt, os_name, arch in combos:
        groups.setdefault((os_name, bt), []).append(arch)
    return groups


def _nacl_pair_arches(
    groups: dict[tuple[str, str], list[str]],
) -> dict[str, list[str]]:
    """Return arches where both NaCl pair blobs are staged."""
    pairs: dict[str, list[str]] = {}
    for (os_name, blob_type), arches in groups.items():
        if blob_type != "nacl_client":
            continue
        server = set(groups.get((os_name, "nacl_server"), []))
        common = sorted(set(arches) & server)
        if common:
            pairs[os_name] = common
    return pairs


def _skip_verify_blob(blob_type: str) -> bool:
    """Return True for non-standalone verify blobs."""
    return blob_type in {
        "nacl_client",
        "nacl_server",
        "nacl_client_hosted",
        "nacl_server_hosted",
    }


def _record_verify_result(
    blob_type: str,
    os_name: str,
    arch: str,
    result,
    summary: _VerifySummary,
) -> None:
    """Record one single-blob verify result."""
    label = f"{os_name}:{arch}"
    out = result.stdout.decode(errors="replace").strip()
    if result.exit_code == 0:
        summary.ok(label, repr(out))
        return
    summary.fail(blob_type, label, f"FAIL exit={result.exit_code:<4d} {out!r}")


def _run_verify_group(
    os_name: str,
    blob_type: str,
    arches: list[str],
    timeout: float,
    summary: _VerifySummary,
) -> None:
    """Run one grouped verify section for a single blob type."""
    click.echo(f"[{os_name}] {blob_type}")
    for arch in sorted(arches):
        label = f"{os_name}:{arch}"
        try:
            result = _verify_one(blob_type, os_name, arch, timeout)
            _record_verify_result(blob_type, os_name, arch, result, summary)
        except _Skip as e:
            summary.skip(label, str(e))
        except Exception as e:  # noqa: BLE001
            summary.fail(blob_type, label, f"ERROR {e}")


def _run_nacl_verify_group(
    os_name: str,
    arches: list[str],
    timeout: float,
    summary: _VerifySummary,
) -> None:
    """Run one grouped NaCl pair verify section."""
    click.echo(f"[{os_name}] nacl e2e")
    for arch in arches:
        label = f"{os_name}:{arch}"
        try:
            detail = _verify_nacl_e2e(os_name, arch, timeout)
            summary.ok(label, detail)
        except _Skip as e:
            summary.skip(label, str(e))
        except Exception as e:  # noqa: BLE001
            summary.fail("nacl_e2e", label, f"FAIL {e}")


def _verify_inner_os(os_name: str) -> str:
    if os_name in {"windows", "freebsd"}:
        return os_name
    return "linux"


def _verify_inner_blob_type(os_name: str, blob_type: str) -> str:
    if os_name == "windows":
        return "hello_windows"
    mapping = {
        "alloc_jump": "test_pass",
        "stager_fd": "test_fd_ok",
        "stager_pipe": "test_pipe_ok",
        "stager_mmap": "test_mmap_ok",
        "stager_tcp": "test_tcp_ok",
    }
    return mapping[blob_type]


def _verify_stager_tcp(os_name: str, arch: str, timeout: float):
    inner = picblobs.get_blob(
        _verify_inner_blob_type(os_name, "stager_tcp"),
        _verify_inner_os(os_name),
        arch,
    )
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        host, port = srv.getsockname()
        payload = _length_prefixed(inner.code)

        def _serve():
            try:
                srv.settimeout(max(timeout, 1.0))
                conn, _ = srv.accept()
                try:
                    conn.sendall(payload)
                finally:
                    conn.close()
            except OSError:
                pass

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        try:
            cfg = struct.pack("<BH", 2, port) + socket.inet_aton(host)
            blob = picblobs.get_blob("stager_tcp", os_name, arch)
            return run_blob(blob, config=cfg, runner_type=os_name, timeout=timeout)
        finally:
            t.join(timeout=5.0)
    finally:
        srv.close()


def _verify_stager_fd(os_name: str, arch: str, timeout: float):
    inner = picblobs.get_blob(
        _verify_inner_blob_type(os_name, "stager_fd"),
        _verify_inner_os(os_name),
        arch,
    )
    cfg = struct.pack("<I", 0)
    blob = picblobs.get_blob("stager_fd", os_name, arch)
    return run_blob(
        blob,
        config=cfg,
        runner_type=os_name,
        timeout=timeout,
        stdin_data=_length_prefixed(inner.code),
    )


def _verify_stager_pipe(os_name: str, arch: str, timeout: float):
    inner = picblobs.get_blob(
        _verify_inner_blob_type(os_name, "stager_pipe"),
        _verify_inner_os(os_name),
        arch,
    )
    tmp = Path(tempfile.mkdtemp(prefix="picblobs_pipe_"))
    fifo = tmp / "payload.fifo"
    _os.mkfifo(str(fifo))
    payload = _length_prefixed(inner.code)

    def _writer():
        try:
            with open(str(fifo), "wb") as f:
                f.write(payload)
        except OSError:
            pass

    t = threading.Thread(target=_writer, daemon=True)
    t.start()
    try:
        path_bytes = str(fifo).encode()
        cfg = struct.pack("<H", len(path_bytes)) + path_bytes
        blob = picblobs.get_blob("stager_pipe", os_name, arch)
        return run_blob(blob, config=cfg, runner_type=os_name, timeout=timeout)
    finally:
        t.join(timeout=5.0)
        try:
            fifo.unlink()
            tmp.rmdir()
        except OSError:
            pass


def _verify_stager_mmap(os_name: str, arch: str, timeout: float):
    inner = picblobs.get_blob(
        _verify_inner_blob_type(os_name, "stager_mmap"),
        _verify_inner_os(os_name),
        arch,
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(inner.code)
        fpath = f.name
    try:
        path_bytes = fpath.encode()
        cfg = (
            struct.pack("<H", len(path_bytes))
            + path_bytes
            + struct.pack("<QQ", 0, len(inner.code))
        )
        blob = picblobs.get_blob("stager_mmap", os_name, arch)
        return run_blob(blob, config=cfg, runner_type=os_name, timeout=timeout)
    finally:
        try:
            Path(fpath).unlink()
        except OSError:
            pass


def _verify_alloc_jump(os_name: str, arch: str, timeout: float):
    inner = picblobs.get_blob(
        _verify_inner_blob_type(os_name, "alloc_jump"),
        _verify_inner_os(os_name),
        arch,
    )
    cfg = struct.pack("<I", len(inner.code)) + inner.code
    blob = picblobs.get_blob("alloc_jump", os_name, arch)
    return run_blob(blob, config=cfg, runner_type=os_name, timeout=timeout)


def _verify_reflective_pe(os_name: str, arch: str, timeout: float):
    dummy = b"MZ" + b"\x00" * 126
    cfg = struct.pack("<IIB", len(dummy), 0, 0) + dummy
    blob = picblobs.get_blob("reflective_pe", os_name, arch)
    return run_blob(blob, config=cfg, runner_type=os_name, timeout=timeout)


def _verify_ul_exec(os_name: str, arch: str, timeout: float):
    from picblobs._cross_compile import build_ul_exec_config, compile_hello_et_exec

    elf_data = compile_hello_et_exec(arch)
    if elf_data is None:
        raise _Skip(f"no cross-compiler for {arch}")
    cfg = build_ul_exec_config(elf_data, arch, argv=["verify"])
    blob = picblobs.get_blob("ul_exec", os_name, arch)
    return run_blob(blob, config=cfg, runner_type=os_name, timeout=timeout)


def _verify_nacl_e2e(os_name: str, arch: str, timeout: float) -> str:
    """Run nacl_server + nacl_client as a paired handshake, return summary."""
    from picblobs.runner import (
        run_blob_pair,
    )

    runner_path = find_runner(os_name, arch)
    server_blob = picblobs.get_blob("nacl_server", os_name, arch)
    client_blob = picblobs.get_blob("nacl_client", os_name, arch)
    result = run_blob_pair(
        server_blob,
        client_blob,
        runner_path,
        os_name,
        timeout=timeout,
    )
    server_out = result.server_stdout
    server_err = result.server_stderr
    client_out = result.client_stdout
    client_err = result.client_stderr

    if result.server_exit != 0:
        raise RuntimeError(
            f"server exit={result.server_exit} stderr={server_err!r}"
        )
    if result.client_exit != 0:
        raise RuntimeError(
            f"client exit={result.client_exit} stderr={client_err!r}"
        )

    if b"Hello from NaCl PIC blob!" not in server_out:
        raise RuntimeError(f"server did not decrypt expected plaintext: {server_out!r}")
    if b"secure channel OK" not in server_out or b"secure channel OK" not in client_out:
        raise RuntimeError("peers did not confirm channel")

    s = server_out.decode(errors="replace")
    c = client_out.decode(errors="replace")
    decrypted = ""
    for line in s.splitlines():
        if "decrypted:" in line:
            decrypted = line.split("decrypted:", 1)[1].strip()
            break
    ack = ""
    for line in c.splitlines():
        if "decrypted ACK:" in line:
            ack = line.split("decrypted ACK:", 1)[1].strip()
            break
    return f"encrypt->send->decrypt {decrypted!r}, ACK {ack!r}"


class _Skip(Exception):
    pass


@main.command()
@click.option("--os", "os_filter", multiple=True, help="Filter by OS")
@click.option("--arch", "arch_filter", multiple=True, help="Filter by arch")
@click.option("--type", "type_filter", multiple=True, help="Filter by blob type")
@click.option("--timeout", type=float, default=30.0, show_default=True)
def verify(
    os_filter: tuple[str, ...],
    arch_filter: tuple[str, ...],
    type_filter: tuple[str, ...],
    timeout: float,
) -> None:
    """Run every staged blob end-to-end (mirrors legacy ``picblobs verify``)."""
    combos = _filter_verify_combos(
        picblobs.list_blobs(),
        os_filter,
        arch_filter,
        type_filter,
    )

    if not combos:
        _fail("no blobs match the given filters")

    summary = _VerifySummary()
    groups = _group_verify_combos(combos)
    nacl_pair_arches = _nacl_pair_arches(groups)

    for (os_name, blob_type), arches in sorted(groups.items()):
        if _skip_verify_blob(blob_type):
            continue
        _run_verify_group(os_name, blob_type, arches, timeout, summary)

    # NaCl e2e handshake runs.
    type_set = set(type_filter)
    if (
        not type_filter
        or "nacl_e2e" in type_set
        or "nacl_client" in type_set
        or "nacl_server" in type_set
    ):
        for os_name, arches in sorted(nacl_pair_arches.items()):
            _run_nacl_verify_group(os_name, arches, timeout, summary)

    summary.emit()
    sys.exit(1 if summary.failed else 0)
