"""picblobs debug CLI — developer tooling for debug builds.

Extends the main picblobs CLI with disassembly and debug-specific
commands. Not shipped in the wheel.

Usage:
    python -m picblobs.debug list
    python -m picblobs.debug info hello linux:x86_64
    python -m picblobs.debug disasm hello linux:x86_64 --function _start
    python -m picblobs.debug disasm hello linux:x86_64
    python -m picblobs.debug listing hello linux:aarch64
    python -m picblobs.debug run hello linux:x86_64
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from picblobs.cli import (
    DEFAULT_TARGET,
    _parse_target,
    _setup_logging,
    cmd_extract,
    cmd_info,
    cmd_list,
    cmd_listing,
    cmd_run,
    cmd_test,
    cmd_verify,
)

log = logging.getLogger("picblobs.debug")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEBUG_BLOB_DIR = PROJECT_ROOT / "debug"


def _find_debug_so(blob_type: str, target_os: str, target_arch: str) -> str | None:
    """Find a debug .so file in the debug staging directory."""
    so = DEBUG_BLOB_DIR / target_os / target_arch / f"{blob_type}.so"
    if so.exists():
        return str(so)
    return None


def _resolve_disasm_so_path(
    blob_type: str,
    target_os: str,
    target_arch: str,
    direct_so: str,
) -> str | None:
    """Return the .so path to inspect, preferring an explicit path."""
    if direct_so:
        return direct_so
    return _find_debug_so(blob_type, target_os, target_arch)


def _load_symbols(so_path: str, objdump: str) -> list[tuple[str, str, str]] | None:
    """Return function symbols or None when the objdump step fails."""
    from picblobs._objdump import list_symbols

    try:
        return list_symbols(so_path, objdump)
    except RuntimeError as e:
        log.error("%s", e)
        return None


def _print_symbols(so_path: str, symbols: list[tuple[str, str, str]]) -> int:
    """Print a function symbol table."""
    if not symbols:
        log.info("No function symbols found in %s", so_path)
        return 0

    fmt = "  {:<16s} {:<10s} {}"
    log.info("Functions in %s:", Path(so_path).name)
    log.info(fmt.format("ADDRESS", "SIZE", "NAME"))
    for addr, size, name in symbols:
        log.info(fmt.format(addr, size, name))
    return 0


# ============================================================
# disasm
# ============================================================


def cmd_disasm(args: argparse.Namespace) -> int:
    """Disassemble a single function or list function symbols."""
    from picblobs._objdump import (
        disassemble_function,
        find_objdump,
        has_debug_info,
        list_symbols,
    )

    target_os, target_arch = _parse_target(args.target)

    so_path = _resolve_disasm_so_path(args.type, target_os, target_arch, args.so)
    if not so_path:
        log.error(
            "Debug .so not found for %s %s:%s. "
            "Build with: python tools/stage_blobs.py --debug",
            args.type,
            target_os,
            target_arch,
        )
        return 1

    if not Path(so_path).exists():
        log.error("File not found: %s", so_path)
        return 1

    try:
        objdump = find_objdump(target_arch)
    except FileNotFoundError as e:
        log.error("%s", e)
        return 1

    has_debug = has_debug_info(so_path, objdump)

    if not args.function:
        # List all function symbols.
        symbols = _load_symbols(so_path, objdump)
        if symbols is None:
            return 1
        return _print_symbols(so_path, symbols)

    # Disassemble a specific function.
    if not has_debug:
        log.error(
            "No DWARF debug info in %s. "
            "Source interleaving requires debug .so files. "
            "Build with: python tools/stage_blobs.py --debug",
            so_path,
        )
        return 1

    try:
        output = disassemble_function(so_path, objdump, args.function, source=True)
    except RuntimeError as e:
        log.error("%s", e)
        return 1

    sys.stdout.write(output)
    return 0


# ============================================================
# debug listing (overrides main CLI listing to prefer debug .so)
# ============================================================


def cmd_debug_listing(args: argparse.Namespace) -> int:
    """Full disassembly listing, preferring debug .so files."""
    from picblobs._objdump import disassemble_full, find_objdump, has_debug_info

    target_os, target_arch = _parse_target(args.target)

    if args.so:
        so_path = args.so
    else:
        # Prefer debug .so, fall back to release.
        so_path = _find_debug_so(args.type, target_os, target_arch)
        if not so_path:
            blob_dir = Path(__file__).parent / "_blobs"
            release_so = blob_dir / target_os / target_arch / f"{args.type}.so"
            if release_so.exists():
                so_path = str(release_so)
                log.info(
                    "# No debug .so found, using release .so (no source interleaving)"
                )
            else:
                log.error(
                    "No .so found for %s %s:%s. "
                    "Build with: python tools/stage_blobs.py [--debug]",
                    args.type,
                    target_os,
                    target_arch,
                )
                return 1

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
# main
# ============================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="picblobs-debug",
        description="picblobs debug CLI — disassembly and developer tooling",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- list ---
    sub.add_parser("list", help="List all blobs in the package")

    # --- info ---
    p_info = sub.add_parser("info", help="Show blob metadata")
    p_info.add_argument("type", nargs="?", default="", help="Blob type")
    p_info.add_argument("target", nargs="?", default=DEFAULT_TARGET, help="os:arch")
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
    p_run = sub.add_parser("run", help="Run a blob under QEMU")
    p_run.add_argument("type", nargs="?", default="", help="Blob type")
    p_run.add_argument("target", nargs="?", default=DEFAULT_TARGET, help="os:arch")
    p_run.add_argument("--so", default="", help="Direct path to .so file")
    p_run.add_argument("--config-hex", default="", help="Config struct as hex string")
    p_run.add_argument("--payload", default="", help="Read config from file")
    p_run.add_argument("--runner-type", default="", help="Runner type override")
    p_run.add_argument("--runner-path", default="", help="Explicit runner path")
    p_run.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds")
    p_run.add_argument("--debug", action="store_true", help="Verbose output")
    p_run.add_argument("--dry-run", action="store_true", help="Print command only")

    # --- verify ---
    p_verify = sub.add_parser("verify", help="Run blob on all architectures")
    p_verify.add_argument("--type", default="hello", help="Blob type")
    p_verify.add_argument("--os", default="linux", help="Target OS")
    p_verify.add_argument("--arch", action="append", default=[], help="Architecture")
    p_verify.add_argument("--timeout", type=float, default=30.0, help="Timeout")

    # --- disasm (debug-only) ---
    p_disasm = sub.add_parser(
        "disasm",
        help="Disassemble a function from a debug .so",
        description=(
            "Disassemble a single function with source interleaving from\n"
            "a debug .so file. Requires debug builds (python tools/stage_blobs.py --debug).\n\n"
            "Without --function, lists all function symbols.\n\n"
            "Examples:\n"
            "  picblobs-debug disasm hello linux:x86_64 --function _start\n"
            "  picblobs-debug disasm hello linux:aarch64\n"
            "  picblobs-debug disasm --so debug/linux/x86_64/hello.so linux:x86_64 -f blob_main\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_disasm.add_argument("type", nargs="?", default="", help="Blob type")
    p_disasm.add_argument("target", nargs="?", default=DEFAULT_TARGET, help="os:arch")
    p_disasm.add_argument(
        "-f", "--function", default="", help="Function name to disassemble"
    )
    p_disasm.add_argument("--so", default="", help="Direct path to .so file")

    # --- listing ---
    p_listing = sub.add_parser(
        "listing",
        help="Full disassembly listing",
        description=(
            "Full disassembly of a blob .so file. Prefers debug .so files\n"
            "(with source interleaving) but falls back to release .so files.\n\n"
            "Examples:\n"
            "  picblobs-debug listing hello linux:x86_64\n"
            "  picblobs-debug listing --so debug/linux/aarch64/hello.so linux:aarch64\n"
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
    p_test.add_argument("pytest_args", nargs="*", default=[], help="Additional args")

    args = parser.parse_args(argv)

    verbose = getattr(args, "debug", False) or getattr(args, "verbose", False)
    _setup_logging(verbose)

    if args.command in ("run", "info", "extract", "disasm", "listing"):
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
        "disasm": cmd_disasm,
        "listing": cmd_debug_listing,
        "test": cmd_test,
    }

    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
