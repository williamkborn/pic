# REQ-012: Custom Per-OS Linker Scripts

## Status
Accepted

## Statement

picblobs SHALL use custom GCC LD linker scripts to produce ELF binaries with a controlled layout suitable for PIC blob extraction. There SHALL be one linker script per target operating system. The linker scripts SHALL define the memory layout, section ordering, and a config section whose symbol is known to the C code but whose content is not included in the extracted blob — it serves as the attachment point for the runtime config struct.

## Rationale

Standard linker scripts produce ELFs intended for OS loaders, with sections, alignment, and metadata that are unnecessary or harmful for PIC blobs. Custom linker scripts give precise control over:
- Section ordering (code first, then read-only data, then the config symbol).
- Elimination of unnecessary sections (dynamic linking metadata, symbol tables, debug info).
- Placement of a config section at a known position, so the C code can reference it via a linker-defined symbol while the Python extraction step knows to exclude it.

## Derives From
- VIS-001

## Detailed Requirements

### Linker Script Per OS

One linker script SHALL exist for each target OS:

- **Linux linker script**: Defines layout for Linux blobs.
- **FreeBSD linker script**: Defines layout for FreeBSD blobs. May be identical to Linux (both produce freestanding code), but is maintained separately to accommodate any future divergence.
- **Windows linker script**: Defines layout for Windows blobs. Despite targeting Windows, the blob is compiled and linked using GCC (Linux-hosted), producing an ELF that is then extracted to flat binary. The linker script ensures the resulting code is correct for Windows execution (no ELF runtime assumptions).

### Section Layout

Each linker script SHALL define the following section ordering:

1. **`.text`**: Executable code. Entry point at the beginning. All function sections (`-ffunction-sections`) are merged here.
2. **`.rodata`**: Read-only data. String literals, constant tables, precomputed hashes. Merged immediately after `.text` so that PC-relative addressing from code to data works with small offsets.
3. **`.data`**: Mutable initialized data. Merged after `.rodata`. In practice, blobs SHOULD minimize mutable global data (use stack instead), so this section may be empty or very small.
4. **`.bss`**: Zero-initialized data. Merged after `.data`. Same note as `.data`.
5. **`.config`**: The config section. This section is defined with a linker symbol at its start (e.g., `__config_start`) that C code can reference as an `extern` symbol. The section is placed last. Its content in the compiled ELF is placeholder/zero bytes of a size matching the config struct definition.

### Linker Symbols

The linker script SHALL export the following symbols:

- `__blob_start`: Address of the beginning of the blob (start of `.text`).
- `__blob_end`: Address of the end of the last section before `.config` (i.e., end of `.bss` or `.data`).
- `__config_start`: Address of the beginning of the `.config` section.
- `__config_end`: Address of the end of the `.config` section.

These symbols enable:
- The C code to reference the config struct via `__config_start`.
- The extraction tool to know exactly which bytes to copy (from `__blob_start` to `__blob_end`) and which to exclude (from `__config_start` to `__config_end`).

### Entry Point

The linker script SHALL set the ELF entry point to the beginning of `.text`, which SHALL be the blob's main entry function. The C source SHALL ensure this function is placed first (via `__attribute__((section(".text.entry")))` or equivalent, with the linker script ordering `.text.entry` before other `.text.*` subsections).

### Dead Code Elimination

The linker script SHALL work in conjunction with `--gc-sections` to eliminate unused functions and data. Only functions reachable from the entry point SHALL be included in the final ELF.

### Alignment

The linker script SHALL specify minimal alignment (1-byte or architecture-required minimum) to avoid unnecessary padding between sections. Blob size is a priority.

### No Standard Sections

The linker script SHALL NOT include standard ELF sections that are unnecessary for the blob:
- No `.interp` (no dynamic linker).
- No `.dynamic` (no dynamic linking).
- No `.plt` / `.got.plt` (no PLT-based function calls).
- No `.eh_frame` / `.eh_frame_hdr` (no exception handling metadata — if GCC emits these, the linker script SHALL discard them via `/DISCARD/`).
- No `.comment`, `.note.*`, or `.debug_*` sections.

## Acceptance Criteria

1. The linked ELF contains only the specified sections in the specified order.
2. The `__config_start` symbol is accessible from C code and points to the correct location.
3. The extraction tool can use ELF section headers or symbol table to identify the code region (`.text` through `.bss`) and the config region (`.config`) precisely.
4. No unnecessary padding exists between sections.
5. No standard ELF runtime sections (`.interp`, `.dynamic`, `.plt`, `.eh_frame`) appear in the output.
6. `--gc-sections` successfully eliminates unreachable code.

## Related Decisions
- ADR-003

## Modeled By
- MOD-003

## Verified By
- TEST-001
- TEST-009
