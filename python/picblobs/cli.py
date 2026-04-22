"""picblobs CLI.

Inspect, extract, run, and verify PIC blobs shipped in the package.

Usage:
    picblobs list
    picblobs info hello linux:x86_64
    picblobs extract hello linux:x86_64 -o blob.bin
    picblobs run hello linux:aarch64
    picblobs verify
    picblobs verify --arch x86_64 --arch mipsel32
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger("picblobs")

DEFAULT_TARGET = "linux:x86_64"


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
    )


def _parse_target(target: str) -> tuple[str, str]:
    """Parse 'os:arch' target string. Returns (os, arch)."""
    if ":" not in target:
        raise ValueError(
            f"Invalid target '{target}'. Expected format: os:arch (e.g., linux:x86_64)"
        )
    parts = target.split(":", 1)
    return parts[0], parts[1]


# ============================================================
# list
# ============================================================


def cmd_list(args: argparse.Namespace) -> int:
    """List all available blobs."""
    from picblobs import list_blobs

    blobs = list_blobs()
    if not blobs:
        log.info("No blobs found in package.")
        return 0

    fmt = "{:<20s} {:<10s} {:<15s}"
    log.info(fmt.format("BLOB TYPE", "OS", "ARCH"))
    log.info(fmt.format("-" * 20, "-" * 10, "-" * 15))
    for blob_type, target_os, target_arch in blobs:
        log.info(fmt.format(blob_type, target_os, target_arch))

    log.info("%d blob(s)", len(blobs))
    return 0


# ============================================================
# info
# ============================================================


def cmd_info(args: argparse.Namespace) -> int:
    """Show blob metadata."""
    from picblobs import get_blob
    from picblobs._extractor import extract

    target_os, target_arch = _parse_target(args.target)

    try:
        if args.so:
            blob = extract(args.so)
        else:
            blob = get_blob(args.type, target_os, target_arch)
    except (FileNotFoundError, ImportError, ValueError) as e:
        log.error("%s", e)
        return 1

    log.info("Blob:           %s", blob.blob_type)
    log.info("OS:             %s", blob.target_os)
    log.info("Arch:           %s", blob.target_arch)
    log.info("Code size:      %d bytes", len(blob.code))
    log.info("Config offset:  %d", blob.config_offset)
    log.info("Entry offset:   %d", blob.entry_offset)
    log.info("SHA-256:        %s", blob.sha256)
    log.info("Sections:")
    for name, (offset, size) in sorted(blob.sections.items()):
        log.info("  %-20s offset=%#06x  size=%#06x", name, offset, size)
    return 0


# ============================================================
# extract
# ============================================================


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract flat blob binary to a file."""
    from picblobs import get_blob
    from picblobs._extractor import extract

    target_os, target_arch = _parse_target(args.target)

    try:
        if args.so:
            blob = extract(args.so)
        else:
            blob = get_blob(args.type, target_os, target_arch)
    except (FileNotFoundError, ImportError, ValueError) as e:
        log.error("%s", e)
        return 1

    output = Path(args.output)
    data = bytearray(blob.code)

    if args.config_hex:
        config = bytes.fromhex(args.config_hex)
        if blob.config_offset > len(data):
            data.extend(b"\x00" * (blob.config_offset - len(data)))
        data[blob.config_offset : blob.config_offset + len(config)] = config

    output.write_bytes(bytes(data))
    log.info("Wrote %d bytes to %s", len(data), output)
    return 0


# ============================================================
# run
# ============================================================


def cmd_run(args: argparse.Namespace) -> int:
    """Run a blob under QEMU via the C test runner."""
    from picblobs import get_blob
    from picblobs._extractor import extract
    from picblobs.runner import run_blob

    config = b""
    if args.config_hex:
        config = bytes.fromhex(args.config_hex)
    elif args.payload:
        config = Path(args.payload).read_bytes()

    runner_path = Path(args.runner_path) if args.runner_path else None
    target_os, target_arch = _parse_target(args.target)

    try:
        if args.so:
            blob = extract(args.so)
        else:
            blob = get_blob(args.type, target_os, target_arch)

        result = run_blob(
            blob,
            config=config,
            runner_type=args.runner_type or "",
            runner_path=runner_path,
            timeout=args.timeout,
            debug=args.debug,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ImportError, ValueError) as e:
        log.error("%s", e)
        return 1

    if args.dry_run:
        log.info(" ".join(result.command))
        return 0

    if result.stdout:
        sys.stdout.buffer.write(result.stdout)
    if result.stderr:
        sys.stderr.buffer.write(result.stderr)

    if args.debug:
        log.debug("exit_code=%d duration=%.3fs", result.exit_code, result.duration_s)

    return result.exit_code


# ============================================================
# verify
# ============================================================


def cmd_verify(args: argparse.Namespace) -> int:
    """Run all staged blobs on every available architecture. The smoke test.

    Discovers what's in the package — no build system knowledge.
    Groups output by OS, then by blob type.

    For ul_exec blobs, compiles a static "Hello, ET_EXEC!" test binary
    per architecture using the Bootlin cross-toolchains, packs it into
    the config, and verifies it executes correctly.
    """
    from picblobs import get_blob, list_blobs
    from picblobs.runner import is_arch_skip_rosetta, run_blob

    filter_types = set(args.type) if args.type else None
    filter_oses = set(args.os) if args.os else None
    filter_arches = set(args.arch) if args.arch else None

    # Discover everything staged in the package.
    available = list_blobs()
    if filter_types:
        available = [(bt, o, a) for bt, o, a in available if bt in filter_types]
    if filter_oses:
        available = [(bt, o, a) for bt, o, a in available if o in filter_oses]
    if filter_arches:
        available = [(bt, o, a) for bt, o, a in available if a in filter_arches]

    if not available:
        log.error("No blobs found. Nothing to verify.")
        log.error("Available blobs:")
        for bt, o, a in list_blobs():
            log.error("  %s %s:%s", bt, o, a)
        return 1

    # Group by (os, blob_type) for readable output.
    groups: dict[tuple[str, str], list[str]] = {}
    for bt, os_name, arch in available:
        groups.setdefault((os_name, bt), []).append(arch)

    passed = 0
    failed = 0
    skipped = 0
    errors = []

    # Blobs that need paired execution or a hosted platform — not standalone.
    _PAIRED_BLOBS = {"nacl_client", "nacl_server"}
    _SKIP_BLOBS = {"nacl_client_hosted", "nacl_server_hosted"}

    # Collect arches where both nacl_client and nacl_server are staged.
    nacl_e2e_arches: dict[str, list[str]] = {}  # os -> [arches]
    for (os_name, blob_type), arches in sorted(groups.items()):
        if blob_type == "nacl_client":
            server_arches = groups.get((os_name, "nacl_server"), [])
            common = sorted(set(arches) & set(server_arches))
            if common:
                nacl_e2e_arches[os_name] = common

    for (os_name, blob_type), arches in sorted(groups.items()):
        if blob_type in _PAIRED_BLOBS or blob_type in _SKIP_BLOBS:
            continue
        log.info("[%s] %s", os_name, blob_type)
        for arch in sorted(arches):
            label = f"{os_name}:{arch}"
            if is_arch_skip_rosetta(arch):
                log.info("  %-20s  SKIP (Rosetta)", label)
                skipped += 1
                continue

            try:
                if blob_type == "ul_exec":
                    result = _verify_ul_exec(
                        os_name,
                        arch,
                        args.timeout,
                    )
                elif blob_type == "stager_tcp":
                    result = _verify_stager_tcp(
                        os_name,
                        arch,
                        args.timeout,
                    )
                elif blob_type == "stager_fd":
                    result = _verify_stager_fd(
                        os_name,
                        arch,
                        args.timeout,
                    )
                elif blob_type == "stager_pipe":
                    result = _verify_stager_pipe(
                        os_name,
                        arch,
                        args.timeout,
                    )
                elif blob_type == "stager_mmap":
                    result = _verify_stager_mmap(
                        os_name,
                        arch,
                        args.timeout,
                    )
                elif blob_type == "alloc_jump":
                    result = _verify_alloc_jump(
                        os_name,
                        arch,
                        args.timeout,
                    )
                elif blob_type == "reflective_pe":
                    result = _verify_reflective_pe(
                        os_name,
                        arch,
                        args.timeout,
                    )
                else:
                    blob = get_blob(blob_type, os_name, arch)
                    result = run_blob(
                        blob,
                        runner_type=os_name,
                        timeout=args.timeout,
                    )

                stdout = result.stdout.decode(errors="replace").strip()
                if result.exit_code == 0:
                    log.info("  %-20s  OK   %r", label, stdout)
                    passed += 1
                else:
                    log.error(
                        "  %-20s  FAIL exit=%-4d %r",
                        label,
                        result.exit_code,
                        stdout,
                    )
                    failed += 1
                    errors.append(f"{blob_type}/{label}")
            except _VerifySkip as e:
                log.info("  %-20s  SKIP (%s)", label, e)
                skipped += 1
            except Exception as e:
                log.error("  %-20s  ERROR: %s", label, e)
                failed += 1
                errors.append(f"{blob_type}/{label}")

    # NaCl e2e: run nacl_server + nacl_client as a pair.
    for os_name, arches in sorted(nacl_e2e_arches.items()):
        log.info("[%s] nacl e2e (server + client encrypted handshake)", os_name)
        for arch in arches:
            label = f"{os_name}:{arch}"
            if is_arch_skip_rosetta(arch):
                log.info("  %-20s  SKIP (Rosetta)", label)
                skipped += 1
                continue
            nacl_timeout = max(args.timeout, 600.0) if args.slow else args.timeout
            try:
                detail = _verify_nacl_e2e(
                    os_name,
                    arch,
                    nacl_timeout,
                    force_slow=args.slow,
                )
                log.info("  %-20s  OK   %s", label, detail)
                passed += 1
            except _VerifySkip as e:
                log.info("  %-20s  SKIP (%s)", label, e)
                skipped += 1
            except Exception as e:
                log.error("  %-20s  FAIL %s", label, e)
                failed += 1
                errors.append(f"nacl_e2e/{label}")

    total = passed + failed + skipped
    log.info("")
    parts = [f"{passed}/{total} passed"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if errors:
        parts.append(f"failed: {', '.join(errors)}")
    log.info("  ".join(parts))
    return 1 if failed else 0


class _VerifySkip(Exception):
    """Raised to skip a verify entry with a reason."""


def _verify_ul_exec(
    os_name: str,
    arch: str,
    timeout: float,
) -> "RunResult":
    """Verify ul_exec by compiling and executing a test ELF.

    Compiles a static 'Hello, ET_EXEC!' binary for the target
    architecture using the Bootlin cross-compiler, packs it into
    the ul_exec config, and runs the blob.
    """
    from picblobs import get_blob
    from picblobs._cross_compile import build_ul_exec_config, compile_hello_et_exec
    from picblobs.runner import RunResult, run_blob

    elf_data = compile_hello_et_exec(arch)
    if elf_data is None:
        raise _VerifySkip(f"no cross-compiler for {arch}")

    blob = get_blob("ul_exec", os_name, arch)
    config = build_ul_exec_config(elf_data, arch, argv=["verify"])
    return run_blob(blob, config=config, timeout=timeout)


def _verify_stager_tcp(
    os_name: str,
    arch: str,
    timeout: float,
) -> "RunResult":
    """Verify stager_tcp end-to-end by serving test_tcp_ok over a local TCP socket.

    Spins up a one-shot localhost TCP server that serves the test_tcp_ok blob
    (``u32 length`` + payload bytes), builds a stager_tcp config pointing at
    it, and runs the stager. The inner payload uses Linux syscalls, so we
    always load test_tcp_ok from the ``linux`` OS regardless of the stager's
    target OS — the translating freebsd runner makes this work uniformly.
    """
    import socket
    import struct
    import threading

    from picblobs import get_blob
    from picblobs.runner import run_blob

    try:
        inner = get_blob("test_tcp_ok", "linux", arch)
    except FileNotFoundError as e:
        raise _VerifySkip(f"test_tcp_ok/linux/{arch} not staged") from e

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        host, port = srv.getsockname()

        payload = struct.pack("<I", len(inner.code)) + inner.code

        def _serve() -> None:
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

        config = struct.pack("<BH", 2, port) + socket.inet_aton(host)
        blob = get_blob("stager_tcp", os_name, arch)
        try:
            return run_blob(blob, config=config, runner_type=os_name, timeout=timeout)
        finally:
            t.join(timeout=5.0)
    finally:
        srv.close()


def _verify_stager_fd(
    os_name: str,
    arch: str,
    timeout: float,
) -> "RunResult":
    """Verify stager_fd by piping a length-prefixed test_fd_ok into stdin."""
    import struct

    from picblobs import get_blob
    from picblobs.runner import run_blob

    try:
        inner = get_blob("test_fd_ok", "linux", arch)
    except FileNotFoundError as e:
        raise _VerifySkip(f"test_fd_ok/linux/{arch} not staged") from e

    config = struct.pack("<I", 0)  # stdin
    stdin_data = struct.pack("<I", len(inner.code)) + inner.code
    blob = get_blob("stager_fd", os_name, arch)
    return run_blob(
        blob,
        config=config,
        runner_type=os_name,
        timeout=timeout,
        stdin_data=stdin_data,
    )


def _verify_stager_pipe(
    os_name: str,
    arch: str,
    timeout: float,
) -> "RunResult":
    """Verify stager_pipe by writing a length-prefixed test_pipe_ok into a FIFO."""
    import os as _os
    import struct
    import tempfile
    import threading

    from picblobs import get_blob
    from picblobs.runner import run_blob

    try:
        inner = get_blob("test_pipe_ok", "linux", arch)
    except FileNotFoundError as e:
        raise _VerifySkip(f"test_pipe_ok/linux/{arch} not staged") from e

    tmpdir = tempfile.mkdtemp(prefix="picblobs_pipe_")
    fifo = Path(tmpdir) / "payload.fifo"
    _os.mkfifo(str(fifo))

    payload = struct.pack("<I", len(inner.code)) + inner.code

    def _writer() -> None:
        try:
            with open(str(fifo), "wb") as f:
                f.write(payload)
        except OSError:
            pass

    t = threading.Thread(target=_writer, daemon=True)
    t.start()
    try:
        path_bytes = str(fifo).encode()
        config = struct.pack("<H", len(path_bytes)) + path_bytes
        blob = get_blob("stager_pipe", os_name, arch)
        return run_blob(blob, config=config, runner_type=os_name, timeout=timeout)
    finally:
        t.join(timeout=5.0)
        try:
            fifo.unlink()
            Path(tmpdir).rmdir()
        except OSError:
            pass


def _verify_stager_mmap(
    os_name: str,
    arch: str,
    timeout: float,
) -> "RunResult":
    """Verify stager_mmap by writing test_mmap_ok to a file and mapping it in."""
    import struct
    import tempfile

    from picblobs import get_blob
    from picblobs.runner import run_blob

    try:
        inner = get_blob("test_mmap_ok", "linux", arch)
    except FileNotFoundError as e:
        raise _VerifySkip(f"test_mmap_ok/linux/{arch} not staged") from e

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(inner.code)
        fpath = f.name

    try:
        path_bytes = fpath.encode()
        config = (
            struct.pack("<H", len(path_bytes))
            + path_bytes
            + struct.pack("<QQ", 0, len(inner.code))
        )
        blob = get_blob("stager_mmap", os_name, arch)
        return run_blob(blob, config=config, runner_type=os_name, timeout=timeout)
    finally:
        try:
            Path(fpath).unlink()
        except OSError:
            pass


def _verify_reflective_pe(
    os_name: str,
    arch: str,
    timeout: float,
) -> "RunResult":
    """Verify reflective_pe by feeding it a minimal MZ-prefixed dummy PE.

    The blob validates the DOS magic, allocates RWX via VirtualAlloc,
    and writes "LOADED\\n" on success. A full PE with section mapping
    and import resolution belongs in a dedicated end-to-end test.
    """
    import struct

    from picblobs import get_blob
    from picblobs.runner import run_blob

    dummy_pe = b"MZ" + b"\x00" * 126
    config = struct.pack("<IIB", len(dummy_pe), 0, 0) + dummy_pe
    blob = get_blob("reflective_pe", os_name, arch)
    return run_blob(blob, config=config, runner_type=os_name, timeout=timeout)


def _verify_alloc_jump(
    os_name: str,
    arch: str,
    timeout: float,
) -> "RunResult":
    """Verify alloc_jump by packing an inner test payload into its config.

    The inner payload writes a known string and exits 0. For Windows blobs
    we use ``hello_windows`` (which drives the mocked WriteFile/ExitProcess
    chain in the windows runner); for unix targets we use ``test_pass``
    (raw syscalls).
    """
    import struct

    from picblobs import get_blob
    from picblobs.runner import run_blob

    if os_name == "windows":
        inner_type, inner_os = "hello_windows", "windows"
    else:
        inner_type, inner_os = "test_pass", "linux"

    try:
        inner = get_blob(inner_type, inner_os, arch)
    except FileNotFoundError as e:
        raise _VerifySkip(f"{inner_type}/{inner_os}/{arch} not staged") from e

    config = struct.pack("<I", len(inner.code)) + inner.code
    blob = get_blob("alloc_jump", os_name, arch)
    return run_blob(blob, config=config, runner_type=os_name, timeout=timeout)


# Architectures where QEMU-emulated TweetNaCl e2e may be slow.
_NACL_E2E_SLOW_ARCHES: frozenset[str] = frozenset()


def _verify_nacl_e2e(
    os_name: str,
    arch: str,
    timeout: float,
    force_slow: bool = False,
) -> str:
    """Verify nacl_client + nacl_server via paired subprocess execution.

    Launches server, waits for bind, launches client. Validates:
      - Both exit 0
      - Server decrypted the expected plaintext
      - Both confirmed secure channel

    Returns a summary string on success.
    Raises _VerifySkip or Exception on failure.
    """
    import struct
    import subprocess

    from picblobs import get_blob
    from picblobs.runner import (
        find_runner,
        reserve_tcp_port,
        run_blob_pair,
    )

    if arch in _NACL_E2E_SLOW_ARCHES and not force_slow:
        is_32 = arch in ("mipsel32", "mipsbe32")
        reason = (
            f"TweetNaCl XSalsa20-Poly1305 uses 64-bit arithmetic — "
            f"{'each 64-bit op becomes multiple 32-bit instructions on ' + arch if is_32 else arch + ' emulation is slow'}, "
            f"all emulated through QEMU; expect 5-10+ minutes"
        )
        raise _VerifySkip(
            f"QEMU {arch} too slow for crypto handshake — {reason}; "
            f"use --slow to force (timeout=600s)"
        )

    runner_path = find_runner(os_name, arch)
    server_blob = get_blob("nacl_server", os_name, arch)
    client_blob = get_blob("nacl_client", os_name, arch)
    port = reserve_tcp_port()
    config = struct.pack("<H", port)
    result = run_blob_pair(
        server_blob,
        client_blob,
        runner_path,
        os_name,
        server_config=config,
        client_config=config,
        timeout=timeout,
    )
    server_stdout = result.server_stdout
    server_stderr = result.server_stderr
    server_exit = result.server_exit
    client_stdout = result.client_stdout
    client_stderr = result.client_stderr
    client_exit = result.client_exit

    # Validate both exited cleanly.
    if server_exit != 0:
        raise RuntimeError(f"server exit={server_exit} stderr={server_stderr!r}")
    if client_exit != 0:
        raise RuntimeError(f"client exit={client_exit} stderr={client_stderr!r}")

    # Validate protocol completed.
    expected_msg = b"Hello from NaCl PIC blob!"
    server_out = server_stdout.decode(errors="replace")
    client_out = client_stdout.decode(errors="replace")

    if expected_msg not in server_stdout:
        raise RuntimeError(f"server did not decrypt expected plaintext: {server_out!r}")
    if b"secure channel OK" not in server_stdout:
        raise RuntimeError(f"server did not confirm channel: {server_out!r}")
    if b"secure channel OK" not in client_stdout:
        raise RuntimeError(f"client did not confirm channel: {client_out!r}")

    # Extract the decrypted message and ACK for display.
    decrypted = ""
    for line in server_out.splitlines():
        if "decrypted:" in line:
            decrypted = line.split("decrypted:", 1)[1].strip()
            break

    ack = ""
    for line in client_out.splitlines():
        if "decrypted ACK:" in line:
            ack = line.split("decrypted ACK:", 1)[1].strip()
            break

    return f"encrypt->send->decrypt '{decrypted}', ACK '{ack}'"


# ============================================================
# listing
# ============================================================


def cmd_listing(args: argparse.Namespace) -> int:
    """Produce a full disassembly listing of a blob .so file."""
    from picblobs._objdump import disassemble_full, find_objdump, has_debug_info

    target_os, target_arch = _parse_target(args.target)

    if args.so:
        so_path = args.so
    else:
        # Listing requires .so files (ELF with debug info).
        # Check _blobs/ (dev) then debug/ directory.
        blob_dir = Path(__file__).parent / "_blobs"
        so_path = str(blob_dir / target_os / target_arch / f"{args.type}.so")
        if not Path(so_path).exists():
            # Try project-root debug/ directory.
            debug_dir = Path(__file__).resolve().parent.parent.parent / "debug"
            alt = str(debug_dir / target_os / target_arch / f"{args.type}.so")
            if Path(alt).exists():
                so_path = alt

    if not Path(so_path).exists():
        log.error("File not found: %s", so_path)
        return 1

    try:
        objdump = find_objdump(target_arch)
    except FileNotFoundError as e:
        log.error("%s", e)
        return 1

    has_debug = has_debug_info(so_path, objdump)
    try:
        output = disassemble_full(so_path, objdump, source=has_debug)
    except RuntimeError as e:
        log.error("%s", e)
        return 1

    sys.stdout.write(output)
    return 0


# ============================================================
# test
# ============================================================


def cmd_test(args: argparse.Namespace) -> int:
    """Run the pytest test suite."""
    import os
    import subprocess

    cmd = [sys.executable, "-m", "pytest"]

    if args.verbose:
        cmd.append("-v")
    if args.filter:
        cmd.extend(["-k", args.filter])

    env = os.environ.copy()
    if args.os:
        env["PICBLOBS_TEST_OS"] = args.os
    if args.arch:
        env["PICBLOBS_TEST_ARCH"] = args.arch
    if args.type:
        env["PICBLOBS_TEST_TYPE"] = args.type

    cmd.extend(args.pytest_args)

    result = subprocess.run(cmd, env=env)
    return result.returncode


# ============================================================
# main
# ============================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="picblobs",
        description="picblobs — inspect, extract, run, and verify PIC blobs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- list ---
    sub.add_parser("list", help="List all blobs in the package")

    # --- info ---
    p_info = sub.add_parser("info", help="Show blob metadata")
    p_info.add_argument("type", nargs="?", default="", help="Blob type (e.g., hello)")
    p_info.add_argument(
        "target",
        nargs="?",
        default=DEFAULT_TARGET,
        help="os:arch (default: linux:x86_64)",
    )
    p_info.add_argument("--so", default="", help="Direct path to .so file")

    # --- extract ---
    p_extract = sub.add_parser("extract", help="Extract flat blob to file")
    p_extract.add_argument("type", nargs="?", default="", help="Blob type")
    p_extract.add_argument("target", nargs="?", default=DEFAULT_TARGET, help="os:arch")
    p_extract.add_argument("-o", "--output", required=True, help="Output file path")
    p_extract.add_argument("--so", default="", help="Direct path to .so file")
    p_extract.add_argument(
        "--config-hex", default="", help="Config struct as hex string"
    )

    # --- run ---
    p_run = sub.add_parser(
        "run",
        help="Run a single blob under QEMU",
        description=(
            "Execute a PIC blob through the C test runner under QEMU user-static.\n\n"
            "Examples:\n"
            "  picblobs run hello                          # linux:x86_64 default\n"
            "  picblobs run hello linux:aarch64             # cross-arch\n"
            "  picblobs run hello linux:x86_64 --debug      # verbose output\n"
            "  picblobs run --so path/to/hello.so           # direct .so file\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_run.add_argument("type", nargs="?", default="", help="Blob type")
    p_run.add_argument(
        "target",
        nargs="?",
        default=DEFAULT_TARGET,
        help="os:arch (default: linux:x86_64)",
    )
    p_run.add_argument("--so", default="", help="Direct path to .so file")
    p_run.add_argument("--config-hex", default="", help="Config struct as hex string")
    p_run.add_argument("--payload", default="", help="Read config from file")
    p_run.add_argument("--runner-type", default="", help="Runner type override")
    p_run.add_argument(
        "--runner-path", default="", help="Explicit path to runner binary"
    )
    p_run.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds")
    p_run.add_argument(
        "--debug", action="store_true", help="Verbose output, keep temp files"
    )
    p_run.add_argument(
        "--dry-run", action="store_true", help="Print command without executing"
    )

    # --- verify ---
    p_verify = sub.add_parser(
        "verify",
        help="Run all staged blobs on every architecture",
        description=(
            "Smoke test: run every staged blob on every architecture available\n"
            "in the package. Discovers what's present — no build system knowledge.\n\n"
            "Examples:\n"
            "  picblobs verify                                # all blobs, all OSes\n"
            "  picblobs verify --arch x86_64 --arch mipsel32  # specific arches\n"
            "  picblobs verify --type hello                    # one blob type\n"
            "  picblobs verify --os linux                      # linux only\n"
            "  picblobs verify --os linux --os windows         # linux + windows\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_verify.add_argument(
        "--type",
        action="append",
        default=[],
        help="Blob type filter (repeatable, default: all)",
    )
    p_verify.add_argument(
        "--os",
        action="append",
        default=[],
        help="Target OS filter (repeatable, default: all)",
    )
    p_verify.add_argument(
        "--arch",
        action="append",
        default=[],
        help="Architecture filter (repeatable, default: all)",
    )
    p_verify.add_argument(
        "--timeout", type=float, default=30.0, help="Per-blob timeout in seconds"
    )
    p_verify.add_argument(
        "--slow",
        action="store_true",
        help="Run slow tests that are skipped by default (e.g., NaCl e2e on MIPS/s390x)",
    )

    # --- listing ---
    p_listing = sub.add_parser(
        "listing",
        help="Full disassembly listing of a blob .so",
        description=(
            "Produce a full disassembly listing via cross-toolchain objdump.\n"
            "Works with release .so files (no source interleaving) or debug\n"
            ".so files (with source interleaving if DWARF info is present).\n\n"
            "Examples:\n"
            "  picblobs listing hello linux:x86_64\n"
            "  picblobs listing --so path/to/hello.so linux:aarch64\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_listing.add_argument("type", nargs="?", default="", help="Blob type")
    p_listing.add_argument("target", nargs="?", default=DEFAULT_TARGET, help="os:arch")
    p_listing.add_argument("--so", default="", help="Direct path to .so file")

    # --- test ---
    p_test = sub.add_parser("test", help="Run pytest test suite")
    p_test.add_argument("--os", default="", help="Filter by OS")
    p_test.add_argument("--arch", default="", help="Filter by architecture")
    p_test.add_argument("--type", default="", help="Filter by blob type")
    p_test.add_argument("-k", "--filter", default="", help="pytest -k expression")
    p_test.add_argument("-v", "--verbose", action="store_true")
    p_test.add_argument(
        "pytest_args", nargs="*", default=[], help="Additional pytest args"
    )

    args = parser.parse_args(argv)

    verbose = getattr(args, "debug", False) or getattr(args, "verbose", False)
    _setup_logging(verbose)

    if args.command in ("run", "info", "extract", "listing"):
        so = getattr(args, "so", "")
        blob_type = getattr(args, "type", "")
        if not so and not blob_type:
            parser.error("Provide a blob type or --so path")

    handlers = {
        "list": cmd_list,
        "info": cmd_info,
        "extract": cmd_extract,
        "run": cmd_run,
        "verify": cmd_verify,
        "listing": cmd_listing,
        "test": cmd_test,
    }

    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
