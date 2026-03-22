"""picblobs developer CLI.

Provides subcommands for inspecting, extracting, and running PIC blobs
during development and testing.

Usage:
    picblobs list
    picblobs info hello linux:x86_64
    picblobs extract hello linux:x86_64 -o blob.bin
    picblobs run hello
    picblobs run hello linux:aarch64 --debug
    picblobs run --so bazel-bin/src/payload/hello.so
    picblobs test -k "alloc_jump"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_TARGET = "linux:x86_64"


def _parse_target(target: str) -> tuple[str, str]:
    """Parse 'os:arch' target string. Returns (os, arch)."""
    if ":" not in target:
        raise argparse.ArgumentTypeError(
            f"Invalid target '{target}'. Expected format: os:arch (e.g., linux:x86_64)"
        )
    parts = target.split(":", 1)
    return parts[0], parts[1]


def cmd_list(args: argparse.Namespace) -> int:
    """List all available blobs."""
    from picblobs import list_blobs

    blobs = list_blobs()
    if not blobs:
        print("No blobs found. Build first: bazel build //src/blob:all")
        return 0

    fmt = "{:<20s} {:<10s} {:<15s}"
    print(fmt.format("BLOB TYPE", "OS", "ARCH"))
    print(fmt.format("-" * 20, "-" * 10, "-" * 15))
    for blob_type, target_os, target_arch in blobs:
        print(fmt.format(blob_type, target_os, target_arch))

    print(f"\n{len(blobs)} blob(s)")
    return 0


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
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Blob:           {blob.blob_type}")
    print(f"OS:             {blob.target_os}")
    print(f"Arch:           {blob.target_arch}")
    print(f"Code size:      {len(blob.code)} bytes")
    print(f"Config offset:  {blob.config_offset}")
    print(f"Entry offset:   {blob.entry_offset}")
    print(f"SHA-256:        {blob.sha256}")
    print(f"Sections:")
    for name, (offset, size) in sorted(blob.sections.items()):
        print(f"  {name:<20s} offset={offset:#06x}  size={size:#06x}")
    return 0


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
        print(f"Error: {e}", file=sys.stderr)
        return 1

    output = Path(args.output)
    data = bytearray(blob.code)

    if args.config_hex:
        config = bytes.fromhex(args.config_hex)
        if blob.config_offset > len(data):
            data.extend(b"\x00" * (blob.config_offset - len(data)))
        data[blob.config_offset:blob.config_offset + len(config)] = config

    output.write_bytes(bytes(data))
    print(f"Wrote {len(data)} bytes to {output}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run a blob under QEMU via the C test runner."""
    from picblobs import get_blob
    from picblobs._extractor import extract
    from picblobs.runner import run_blob

    # Build config bytes.
    config = b""
    if args.config_hex:
        config = bytes.fromhex(args.config_hex)
    elif args.payload:
        config = Path(args.payload).read_bytes()

    runner_path = Path(args.runner_path) if args.runner_path else None

    target_os, target_arch = _parse_target(args.target)

    try:
        if args.so:
            # Direct .so mode — extract with explicit os/arch from target.
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
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(" ".join(result.command))
        return 0

    # Print output.
    if result.stdout:
        sys.stdout.buffer.write(result.stdout)
    if result.stderr:
        sys.stderr.buffer.write(result.stderr)

    if args.debug:
        print(f"\n--- exit_code={result.exit_code} duration={result.duration_s:.3f}s ---",
              file=sys.stderr)

    return result.exit_code


def cmd_build(args: argparse.Namespace) -> int:
    """Build and stage all blobs for all platforms."""
    import subprocess

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent.parent.parent / "tools" / "stage_blobs.py"),
    ]

    if args.targets:
        cmd.extend(["--targets"] + args.targets)
    if args.configs:
        cmd.extend(["--configs"] + args.configs)

    result = subprocess.run(cmd)
    return result.returncode


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="picblobs",
        description="picblobs developer CLI — inspect, extract, and run PIC blobs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- list ---
    sub.add_parser("list", help="List all available blobs")

    # --- info ---
    p_info = sub.add_parser("info", help="Show blob metadata")
    p_info.add_argument("type", nargs="?", default="", help="Blob type (e.g., hello)")
    p_info.add_argument("target", nargs="?", default=DEFAULT_TARGET, help="Target as os:arch (default: linux:x86_64)")
    p_info.add_argument("--so", default="", help="Direct path to .so file")

    # --- extract ---
    p_extract = sub.add_parser("extract", help="Extract flat blob to file")
    p_extract.add_argument("type", nargs="?", default="", help="Blob type")
    p_extract.add_argument("target", nargs="?", default=DEFAULT_TARGET, help="Target as os:arch")
    p_extract.add_argument("-o", "--output", required=True, help="Output file path")
    p_extract.add_argument("--so", default="", help="Direct path to .so file")
    p_extract.add_argument("--config-hex", default="", help="Config struct as hex string")

    # --- run ---
    p_run = sub.add_parser(
        "run",
        help="Run a blob under QEMU via the C test runner",
        description=(
            "Execute a PIC blob through the C test runner under QEMU user-static.\n\n"
            "Examples:\n"
            "  picblobs run hello                          # linux:x86_64 default\n"
            "  picblobs run hello linux:aarch64             # cross-arch\n"
            "  picblobs run hello linux:x86_64 --debug      # verbose output\n"
            "  picblobs run --so bazel-bin/src/payload/hello.so  # direct .so\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_run.add_argument("type", nargs="?", default="", help="Blob type (e.g., hello, alloc_jump)")
    p_run.add_argument("target", nargs="?", default=DEFAULT_TARGET, help="Target as os:arch (default: linux:x86_64)")
    p_run.add_argument("--so", default="", help="Direct path to .so file (bypasses type/target)")
    p_run.add_argument("--config-hex", default="", help="Config struct as hex string")
    p_run.add_argument("--payload", default="", help="Read config from file")
    p_run.add_argument("--runner-type", default="", help="Runner type override (linux/freebsd/windows)")
    p_run.add_argument("--runner-path", default="", help="Explicit path to runner binary")
    p_run.add_argument("--timeout", type=float, default=30.0, help="Execution timeout in seconds")
    p_run.add_argument("--debug", action="store_true", help="Verbose output, keep temp files")
    p_run.add_argument("--dry-run", action="store_true", help="Print command without executing")

    # --- build ---
    p_build = sub.add_parser(
        "build",
        help="Build and stage blobs for all platforms",
        description="Build blob .so files for all platforms and stage into the package tree.",
    )
    p_build.add_argument("targets", nargs="*", default=[], help="Blob names to build (default: all)")
    p_build.add_argument("--configs", nargs="*", default=[], help="Platform configs as os:arch (default: all)")

    # --- test ---
    p_test = sub.add_parser("test", help="Run pytest test suite")
    p_test.add_argument("--os", default="", help="Filter tests by target OS")
    p_test.add_argument("--arch", default="", help="Filter tests by architecture")
    p_test.add_argument("--type", default="", help="Filter tests by blob type")
    p_test.add_argument("-k", "--filter", default="", help="pytest -k filter expression")
    p_test.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    p_test.add_argument("pytest_args", nargs="*", default=[], help="Additional pytest arguments")

    args = parser.parse_args(argv)

    # Validate: run/info/extract need either --so or a blob type.
    if args.command in ("run", "info", "extract"):
        so = getattr(args, "so", "")
        blob_type = getattr(args, "type", "")
        if not so and not blob_type:
            parser.error(f"Provide a blob type or --so path")

    handlers = {
        "list": cmd_list,
        "info": cmd_info,
        "extract": cmd_extract,
        "run": cmd_run,
        "build": cmd_build,
        "test": cmd_test,
    }

    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
