# REQ-013: ELF-to-Blob Extraction via pyelftools

## Status
Accepted

## Statement

picblobs SHALL use a Python-based extraction tool built on the pyelftools library to convert linked ELF binaries (produced by the custom linker scripts per REQ-012) into flat PIC blob binaries. The extraction tool SHALL copy the code and data sections from the ELF while excluding the config section, producing a minimal flat binary that is ready to have a config struct appended at runtime by the Python API.

## Rationale

Using pyelftools (rather than `objcopy -O binary`) gives precise, programmable control over which sections are extracted and how they are laid out. It also allows the extraction tool to emit metadata (section offsets, config struct offset, blob size) that the Python packaging step needs for the introspection API (REQ-016). The extraction tool runs as a Bazel genrule, keeping the entire pipeline within the Bazel build graph.

## Derives From
- REQ-012

## Detailed Requirements

### Extraction Process

The extraction tool SHALL:

1. Open the input ELF file using pyelftools.
2. Locate the sections defined by the linker script: `.text`, `.rodata`, `.data`, `.bss`, and `.config`.
3. Determine the extraction range: from the start of `.text` to the end of the last section before `.config` (i.e., the `__blob_start` to `__blob_end` range, resolved from the ELF symbol table or section headers).
4. Read the raw bytes of the code and data sections, preserving their relative offsets (accounting for alignment between sections).
5. For `.bss`: emit zero bytes for the BSS region's size (since BSS has no content in the ELF file, but the blob may need zero-initialized memory at a known offset).
6. Write the concatenated bytes to the output flat binary file.
7. Do NOT include the `.config` section content in the output. The config section's symbol offset relative to `__blob_start` SHALL be recorded in metadata (see below).

### Metadata Emission

Alongside each flat blob binary, the extraction tool SHALL emit a metadata file (JSON or YAML) containing:

1. **blob_size**: Total size of the flat binary in bytes.
2. **config_offset**: Byte offset from the start of the blob where the config section would begin (i.e., the value of `__config_start - __blob_start`). This is where the Python API appends the config struct.
3. **entry_offset**: Byte offset of the entry point within the blob (normally 0, since `.text` starts at the beginning, but recorded explicitly).
4. **sections**: A list of sections with their offsets and sizes within the flat binary (for introspection).
5. **target_os**: The target OS this blob was built for.
6. **target_arch**: The target architecture.
7. **blob_type**: The blob type (alloc-jump, reflective-elf, reflective-pe, stager-tcp, etc.).
8. **build_hash**: A hash (SHA256) of the blob binary for integrity verification.

### Validation

The extraction tool SHALL validate:

1. The ELF contains the expected sections (at minimum `.text` and `.config`).
2. The `__blob_start`, `__blob_end`, and `__config_start` symbols exist in the symbol table.
3. The extracted code region contains no absolute address relocations (the ELF should have been fully linked with no remaining relocations — any unresolved relocations indicate a build error).
4. The blob is non-empty.

If validation fails, the tool SHALL exit with a non-zero status and a descriptive error message, causing the Bazel build to fail.

### Integration with Bazel

The extraction tool SHALL be invocable as a Bazel genrule or custom rule:

- Input: The linked ELF binary (output of the linker step).
- Outputs: The flat blob binary file and the metadata JSON/YAML file.
- The rule SHALL declare both outputs so that downstream targets (Python wheel packaging) can depend on them.

### BSS Handling

If the blob has a `.bss` section (zero-initialized data), the extraction tool SHALL:

1. Include the BSS region as zero bytes in the flat binary, OR
2. Record the BSS offset and size in metadata and let the blob's runtime initialization zero it (e.g., the blob entry point zeros its own BSS using a memset-equivalent before proceeding).

Option 1 (include zeros in the binary) is RECOMMENDED for simplicity, at the cost of slightly larger blob files. Option 2 is acceptable if blob size is critical.

## Acceptance Criteria

1. The extraction tool produces a flat binary that, when loaded at an arbitrary address, executes correctly as PIC.
2. The metadata file accurately reflects the blob's layout (verified by comparing against ELF section headers).
3. The config offset in metadata matches the actual position where the C code expects the config struct (verified by cross-referencing with the `__config_start` symbol).
4. The tool rejects invalid ELFs (missing sections, unresolved relocations) with clear error messages.
5. The tool runs successfully as a Bazel genrule for every target in the build matrix.

## Related Decisions
- ADR-007

## Verified By
- TEST-001
