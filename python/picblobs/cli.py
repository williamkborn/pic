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
    except (FileNotFoundError, ValueError) as e:
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
    except (FileNotFoundError, ValueError) as e:
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
            blob = extract(args.so, target_os=target_os, target_arch=target_arch)
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
    except (FileNotFoundError, ValueError) as e:
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
    from picblobs.runner import is_arch_skip_rosetta, run_blob, run_so

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

    blob_dir = Path(__file__).parent / "_blobs"
    for (os_name, blob_type), arches in sorted(groups.items()):
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
                        os_name, arch, args.timeout,
                    )
                else:
                    so = blob_dir / os_name / arch / f"{blob_type}.so"
                    result = run_so(
                        str(so), runner_type=os_name, timeout=args.timeout,
                    )

                stdout = result.stdout.decode(errors="replace").strip()
                if result.exit_code == 0:
                    log.info("  %-20s  OK   %r", label, stdout)
                    passed += 1
                else:
                    log.error(
                        "  %-20s  FAIL exit=%-4d %r",
                        label, result.exit_code, stdout,
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
    os_name: str, arch: str, timeout: float,
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
        blob_dir = Path(__file__).parent / "_blobs"
        so_path = str(blob_dir / target_os / target_arch / f"{args.type}.so")

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
