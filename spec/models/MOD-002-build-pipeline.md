# MOD-002: Build Pipeline

## Status
Accepted

## Description

This model describes the complete build pipeline from C source to Python wheel. Each stage in the pipeline is a Bazel action or a step in the wheel build process.

## Pipeline Stages

### Stage 1: Toolchain Provisioning

- **Trigger**: First Bazel build or cache miss.
- **Action**: Bazel fetches Bootlin cross-compiler archives from toolchains.bootlin.com.
- **Output**: Extracted toolchain directories in Bazel's external repository cache.
- **Artifacts**: GCC binaries, binutils, headers for each architecture.

### Stage 2: C Compilation

- **Input**: C source files (syscall wrappers, PEB walk, blob logic), assembly stubs, C config headers.
- **Action**: For each target platform (OS/arch combination), the corresponding Bootlin GCC cross-compiler compiles C and assembles the assembly stub.
- **Flags**: `-ffreestanding -nostdlib -nostartfiles -fno-builtin -fPIC -ffunction-sections -fdata-sections -Os -Wall -Werror` plus architecture-specific flags.
- **Output**: Object files (`.o`) for each source file, per platform.

### Stage 3: Linking

- **Input**: Object files from Stage 2, custom linker script for the target OS (REQ-012).
- **Action**: The GCC linker (`ld`) links the object files using the custom linker script with `--gc-sections` to eliminate dead code.
- **Output**: A linked ELF binary with the controlled section layout (`.text`, `.rodata`, `.data`, `.bss`, `.config`) and exported symbols (`__blob_start`, `__blob_end`, `__config_start`).

### Stage 4: ELF Extraction

- **Input**: Linked ELF from Stage 3.
- **Action**: The pyelftools-based extraction tool (REQ-013) reads the ELF, copies the code/data sections (excluding `.config`), and emits a flat binary and a metadata JSON file.
- **Output**: `{blob_type}.bin` and `{blob_type}.meta.json` for each OS/arch/blob-type combination.
- **Validation**: The tool verifies expected sections exist, symbols are present, and no unresolved relocations remain.

### Stage 5: Config Codegen

- **Input**: C config header files (`config/*.h`).
- **Action**: The pycparser-based codegen tool (REQ-014) parses the headers and emits Python `ctypes.Structure` subclasses.
- **Output**: `picblobs/_generated/configs.py` (or multiple files).

### Stage 6: Asset Assembly

- **Input**: All `.bin` and `.meta.json` files from Stage 4, generated Python files from Stage 5.
- **Action**: Copy artifacts into the Python package directory structure (`picblobs/_blobs/`, `picblobs/_generated/`).
- **Output**: Complete Python package source tree ready for wheel build.

### Stage 7: Wheel Build

- **Input**: Complete Python package source tree.
- **Action**: `uv build` (or equivalent) produces a wheel.
- **Output**: `picblobs-X.Y.Z-py3-none-any.whl`.

## Parallelism

Stages 2-4 are per-target and are executed in parallel by Bazel for all 96 targets. Stage 5 is independent of Stages 2-4 and can run in parallel. Stage 6 depends on all of 2-4 and 5. Stage 7 depends on 6.

## Build Matrix Size

- 18 platforms (7 Linux arches + 7 FreeBSD arches + 2 Windows arches + 2 armv5 Thumb variants for Linux/FreeBSD = adjusted per REQ-018)
- 6 blob types per platform (except Windows which has Reflective PE instead of Reflective ELF)
- 96 total blob binaries
- 96 total metadata files
- ~6-10 config struct definitions (shared across blob types)
- 1 generated Python config module
- 1 wheel

## Derives From
- REQ-011
- REQ-012
- REQ-013
- REQ-014
- REQ-017
