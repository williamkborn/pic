# REQ-013: Runtime ELF-to-Blob Extraction via pyelftools

## Status
Accepted (amended Sprint 1 — changed from build-time to runtime extraction per ADR-018)

## Statement

picblobs SHALL use pyelftools as a runtime dependency to extract flat PIC blob code from `.so` shared objects on demand. The extraction reads `__blob_start`, `__blob_end`, and `__config_start` symbols from the `.symtab` section, copies allocated section data from the symbol-delimited range, and returns a `BlobData` object with the flat code bytes and metadata.

## Rationale

Shipping `.so` files directly (ADR-018) and extracting at runtime eliminates a build pipeline stage, preserves ELF metadata for introspection, and keeps extraction logic in Python where it is easier to test and debug.

## Derives From
- VIS-001

## Detailed Requirements

### Extraction Process

The `picblobs._extractor.extract()` function SHALL:

1. Open the `.so` file and parse it as an ELF via `elftools.elf.elffile.ELFFile`.
2. Locate the `.symtab` section. Raise `ValueError` if absent.
3. Find symbols `__blob_start`, `__blob_end`, `__config_start`. Raise `ValueError` if any is missing.
4. Read bytes from all `SHF_ALLOC` sections whose `sh_addr` falls within `[__blob_start, __blob_end)`.
5. For `SHT_NOBITS` sections (`.bss`), emit zero bytes.
6. Skip non-allocated sections (`.symtab`, `.strtab`, `.shstrtab`).
7. Return a `BlobData` dataclass.

### BlobData Fields

| Field | Type | Description |
|---|---|---|
| `code` | `bytes` | Flat code bytes from `__blob_start` to `__blob_end` |
| `config_offset` | `int` | `__config_start - __blob_start` |
| `entry_offset` | `int` | Entry point offset (0) |
| `blob_type` | `str` | Blob type identifier |
| `target_os` | `str` | Target operating system |
| `target_arch` | `str` | Target architecture |
| `sha256` | `str` | SHA-256 hex digest of `code` |
| `sections` | `dict` | Section name → (offset, size) for allocated sections |

### Path Convention

Blob `.so` files are stored in the Python package at:

```
picblobs/_blobs/{os}/{arch}/{blob_type}.so
```

If `blob_type`, `target_os`, or `target_arch` are not provided to `extract()`, they are derived from the file path.

### Caching

`picblobs.get_blob()` caches extraction results via `functools.lru_cache`. Repeated calls for the same blob return the same `BlobData` instance without re-reading the `.so`.

## Acceptance Criteria

1. `extract()` correctly reads `.so` files produced by the Bazel build pipeline.
2. Extracted `code` bytes execute correctly when loaded at any address (verified on all 6 architectures).
3. `config_offset` matches the actual `__config_start` symbol value minus `__blob_start`.
4. Non-allocated sections are not included in the extracted bytes.
5. Missing `.symtab` or required symbols raise `ValueError` with descriptive messages.

## Related Decisions
- ADR-018 (supersedes ADR-007)

## Verified By
- TEST-001
