"""Runtime ELF section extractor for .so blob files.

Uses pyelftools to read __blob_start/__blob_end/__config_start symbols
from .so files and extract the flat code bytes on demand.

The .so files are cross-compiled freestanding shared objects with a
custom linker script that controls section layout:
  .text → .rodata → .data → .bss → .config

This module reads the ELF, locates the symbol-delimited range, and
returns the raw bytes as a flat PIC blob ready for execution.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection


@dataclasses.dataclass(frozen=True)
class BlobData:
    """Extracted blob bytes and metadata from a .so file."""

    code: bytes
    """Flat code bytes from __blob_start to __blob_end."""

    config_offset: int
    """Offset of __config_start relative to __blob_start."""

    entry_offset: int
    """Offset of the entry point (normally 0)."""

    blob_type: str
    """Blob type identifier (e.g., 'alloc_jump')."""

    target_os: str
    """Target operating system (e.g., 'linux')."""

    target_arch: str
    """Target architecture (e.g., 'x86_64')."""

    sha256: str
    """SHA-256 hex digest of the code bytes."""

    sections: dict[str, tuple[int, int]]
    """Section name → (offset_from_blob_start, size)."""


def _find_symbol(symtab: SymbolTableSection, name: str) -> int:
    """Return the value of a symbol by name, or raise ValueError."""
    for sym in symtab.iter_symbols():
        if sym.name == name:
            return sym.entry.st_value
    raise ValueError(f"Symbol '{name}' not found in .symtab")


def _read_range(elf: ELFFile, start: int, end: int) -> bytearray:
    """Read bytes from ELF sections covering [start, end).

    For SHT_PROGBITS sections, copies raw data.
    For SHT_NOBITS sections (.bss), fills with zeros.
    """
    size = end - start
    buf = bytearray(size)

    for section in elf.iter_sections():
        sh_flags = section.header.sh_flags
        sh_addr = section.header.sh_addr
        sh_size = section.header.sh_size
        sh_type = section.header.sh_type

        # Only process allocated sections (skip .symtab, .strtab, etc.)
        if not (sh_flags & 0x2):  # SHF_ALLOC
            continue

        if sh_size == 0:
            continue

        # Check if this section overlaps [start, end).
        sec_start = sh_addr
        sec_end = sh_addr + sh_size
        overlap_start = max(sec_start, start)
        overlap_end = min(sec_end, end)

        if overlap_start >= overlap_end:
            continue

        buf_offset = overlap_start - start

        if sh_type == "SHT_NOBITS":
            # BSS — already zero in the bytearray.
            pass
        else:
            data = section.data()
            data_offset = overlap_start - sec_start
            length = overlap_end - overlap_start
            buf[buf_offset:buf_offset + length] = data[data_offset:data_offset + length]

    return buf


def _collect_sections(
    elf: ELFFile, blob_start: int, blob_end: int,
) -> dict[str, tuple[int, int]]:
    """Collect section offsets relative to blob_start."""
    result = {}
    for section in elf.iter_sections():
        sh_flags = section.header.sh_flags
        sh_addr = section.header.sh_addr
        sh_size = section.header.sh_size
        name = section.name

        if not (sh_flags & 0x2):  # SHF_ALLOC only
            continue
        if sh_size == 0 or not name:
            continue
        if sh_addr < blob_start or sh_addr >= blob_end:
            continue

        result[name] = (sh_addr - blob_start, sh_size)

    return result


def extract(
    so_path: str | Path,
    blob_type: str = "",
    target_os: str = "",
    target_arch: str = "",
) -> BlobData:
    """Extract flat blob bytes and metadata from a .so file.

    Args:
        so_path: Path to the .so blob file.
        blob_type: Blob type override. If empty, derived from filename.
        target_os: Target OS override. If empty, derived from path.
        target_arch: Target arch override. If empty, derived from path.

    Returns:
        BlobData with extracted code bytes and metadata.

    Raises:
        ValueError: If required symbols or sections are missing.
        FileNotFoundError: If so_path does not exist.
    """
    so_path = Path(so_path)

    # Derive blob_type/os/arch from path if not provided.
    # Expected layout: .../_blobs/{os}/{arch}/{blob_type}.so
    if not blob_type or not target_os or not target_arch:
        parts = so_path.parts
        if len(parts) >= 3:
            if not target_arch:
                target_arch = parts[-2]
            if not target_os:
                target_os = parts[-3]
        if not blob_type:
            blob_type = so_path.stem

    with open(so_path, "rb") as f:
        elf = ELFFile(f)

        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            raise ValueError(f"No .symtab in {so_path}")

        blob_start = _find_symbol(symtab, "__blob_start")
        blob_end = _find_symbol(symtab, "__blob_end")
        config_start = _find_symbol(symtab, "__config_start")

        code = bytes(_read_range(elf, blob_start, blob_end))
        sections = _collect_sections(elf, blob_start, blob_end)

    return BlobData(
        code=code,
        config_offset=config_start - blob_start,
        entry_offset=0,
        blob_type=blob_type,
        target_os=target_os,
        target_arch=target_arch,
        sha256=hashlib.sha256(code).hexdigest(),
        sections=sections,
    )
