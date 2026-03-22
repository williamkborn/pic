#!/usr/bin/env python3
"""Config struct codegen tool (REQ-014, ADR-004).

Parses C config header files and generates Python ctypes.Structure
subclasses for serializing config structs to append to blob binaries.

Usage:
    config_codegen.py --input config.h --output configs.py
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Python config structs from C headers"
    )
    parser.add_argument("--input", required=True, help="Input C header file")
    parser.add_argument("--output", required=True, help="Output Python file")
    args = parser.parse_args()

    # TODO: implement pycparser-based codegen
    try:
        import pycparser  # noqa: F401
    except ImportError:
        print("pycparser not installed — stub mode", file=sys.stderr)

    # Stub: emit an empty module.
    with open(args.output, "w") as f:
        f.write('"""Auto-generated config struct bindings."""\n')
        f.write(f"# Generated from: {args.input}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
