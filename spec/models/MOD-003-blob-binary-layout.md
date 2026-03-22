# MOD-003: Blob Binary Layout

## Status
Accepted

## Description

This model describes the internal memory layout of a picblobs PIC blob at three stages: as a linked ELF, as an extracted flat binary, and as a fully-assembled blob with config struct appended by the Python API.

## Stage 1: Linked ELF (output of linker)

```
+==========================================+
| ELF Header                               |  <- Standard ELF header (not part of blob)
+------------------------------------------+
| Program Headers                          |  <- Describe segments (not part of blob)
+==========================================+
| .text                                    |  <- Entry point at offset 0 of this section
|   .text.entry (blob entry function)      |     Ordered first by linker script
|   .text.* (all other code)               |     Merged from -ffunction-sections
+------------------------------------------+
| .rodata                                  |  <- String literals, constant tables,
|   Precomputed DJB2 hashes (Windows)      |     hash values, lookup tables
|   Syscall number constants (if in rodata)|
+------------------------------------------+
| .data                                    |  <- Mutable initialized globals
|   (typically empty or very small)        |     Blobs should prefer stack variables
+------------------------------------------+
| .bss                                     |  <- Zero-initialized globals
|   (typically empty or very small)        |     Used for resolved function pointer cache
+------------------------------------------+
| .config                                  |  <- Config section
|   __config_start symbol points here      |     Placeholder bytes matching struct size
|   Config struct placeholder (zeroed)     |     C code references via extern symbol
|   __config_end symbol points here        |
+==========================================+
| Section Headers                          |  <- ELF section metadata (not part of blob)
| Symbol Table                             |  <- Contains __blob_start, __blob_end, etc.
+==========================================+

Linker-exported symbols:
  __blob_start  = start of .text
  __blob_end    = end of .bss (or .data if no .bss)
  __config_start = start of .config
  __config_end   = end of .config
```

## Stage 2: Extracted Flat Binary (output of pyelftools tool)

```
Offset 0x0000:
+==========================================+
| .text content                            |  <- Raw machine code, entry at offset 0
|   Entry function                         |
|   Syscall wrappers (only used ones)      |
|   PEB walk (Windows blobs only)          |
|   Blob-specific logic                    |
+------------------------------------------+
| .rodata content                          |  <- Immediately follows .text
|   Constants, hash tables                 |
+------------------------------------------+
| .data content (if any)                   |  <- Follows .rodata
+------------------------------------------+
| .bss zero bytes (if any)                 |  <- Follows .data (zeros in flat binary)
+==========================================+
  ^                                        ^
  |                                        |
  blob_start (offset 0)                    config_offset (recorded in metadata)

Metadata JSON emitted alongside:
{
  "blob_size": <size of this flat binary>,
  "config_offset": <byte offset where config should be appended>,
  "entry_offset": 0,
  "sections": [...],
  "target_os": "linux",
  "target_arch": "x86_64",
  "blob_type": "alloc_jump",
  "build_hash": "<sha256>"
}

Note: config_offset == blob_size in the normal case (config is appended
at the end). They may differ if .bss is included in the binary but the
config attaches after .bss.
```

## Stage 3: Fully Assembled Blob (output of Python API `.build()`)

```
Offset 0x0000:
+==========================================+
| Extracted flat binary                    |  <- Copied from wheel's bundled .bin file
| (code + rodata + data + bss)             |
+==========================================+
| Config struct (serialized by Python)     |  <- Appended at config_offset
|   version: uint16                        |     Serialized via struct.pack (ADR-009)
|   [blob-type-specific fixed fields]      |     Native endianness of target arch
|   (includes length fields for each       |
|    variable-length region below)         |
|------------------------------------------|
|   [variable-length trailing data]        |     Inline, immediately after fixed fields
|   (payload bytes, paths, etc.)           |     In declaration order, no padding
|   Variable data runs to end of config    |
+==========================================+

This is the final bytes object returned by .build().
The blob's __config_start reference (a PC-relative offset
baked in at compile time) points exactly to the start of
the config struct region.
```

## PC-Relative Config Access

The C code accesses the config struct as:

```
(conceptual, not actual code)
extern struct config __config_start;
// The compiler emits a PC-relative load to the offset
// where .config was placed by the linker script.
// Since the blob is position-independent, this offset
// is relative to the current instruction pointer and
// remains valid regardless of where the blob is loaded.
```

The critical invariant: the byte distance from any instruction in `.text` to `__config_start` is fixed at link time and does not change when the blob is loaded at an arbitrary address. This is guaranteed by PIC compilation (`-fPIC`) and the linker script's deterministic section ordering.

## Derives From
- REQ-012
- REQ-013
- REQ-014
