"""Verify PIC blob ELF invariants with a declared readelf binary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _readelf(readelf: Path, *args: str) -> str:
    result = subprocess.run(
        [str(readelf), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def _sym_addr(symtab: str, name: str) -> str | None:
    for line in symtab.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[-1] == name:
            return fields[1]
    return None


def _machine(header: str) -> str:
    for line in header.splitlines():
        if "Machine:" in line:
            return line.split("Machine:", 1)[1].strip().split()[0]
    return ""


def _check_blob(readelf: Path, blob: Path) -> list[str]:
    failures: list[str] = []
    name = blob.name
    print(f"--- Checking {name} ---")
    if not blob.is_file():
        return [f"{name}: file not found: {blob}"]

    sections = _readelf(readelf, "-S", str(blob))
    reloc_count = sum(
        1 for line in sections.splitlines() if ".rel." in line or ".rela." in line
    )
    if reloc_count:
        failures.append(f"{name}: found {reloc_count} relocation section(s)")
    else:
        print("  OK: no relocation sections")

    symtab = _readelf(readelf, "-s", str(blob))
    start_addr = _sym_addr(symtab, "__blob_start")
    end_addr = _sym_addr(symtab, "__blob_end")
    if start_addr:
        print("  OK: __blob_start found")
    else:
        failures.append(f"{name}: missing __blob_start symbol")
    if end_addr:
        print("  OK: __blob_end found")
    else:
        failures.append(f"{name}: missing __blob_end symbol")

    if start_addr in {"00000000", "0000000000000000"}:
        print("  OK: __blob_start at address 0")
    else:
        failures.append(f"{name}: __blob_start at {start_addr or '?'} (expected 0)")

    if end_addr:
        blob_size = int(end_addr, 16)
        if blob_size <= 102400:
            print(f"  OK: blob size {blob_size} bytes ({blob_size // 1024}KB < 100KB)")
        else:
            failures.append(f"{name}: blob size {blob_size} bytes exceeds 100KB")

    header = _readelf(readelf, "-h", str(blob))
    machine = _machine(header)
    if machine == "ARM":
        print("  OK: ARM ELF")
    else:
        failures.append(f"{name}: expected ARM ELF, got machine={machine}")
    return failures


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.stderr.write("Usage: verify_pic.py <readelf> <blob.so> [<blob.so> ...]\n")
        return 2
    readelf = Path(argv[1])
    failures: list[str] = []
    for blob_arg in argv[2:]:
        failures.extend(_check_blob(readelf, Path(blob_arg)))
        print()
    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1
    print("=== ALL CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
