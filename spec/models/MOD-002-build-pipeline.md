# MOD-002: Build Pipeline

## Status
Accepted (amended Sprint 1)

## Description

This model describes the complete build pipeline from C source to staged Python package. The pipeline produces cross-compiled `.so` shared objects for all target platforms, cross-compiled test runners, and stages both into the Python package tree.

## Pipeline Stages

### Stage 1: Toolchain Provisioning

- **Trigger**: First Bazel build or cache miss.
- **Action**: Bazel fetches Bootlin cross-compiler archives from toolchains.bootlin.com via the `bootlin` module extension.
- **Output**: Extracted toolchain directories in Bazel's external repository cache, with generated `cc_toolchain_config` and `BUILD.bazel` per toolchain.
- **Artifacts**: GCC 13.3.0 binaries, binutils, headers for each architecture.

### Stage 2: C Compilation

- **Input**: C source files (syscall wrappers, blob logic), assembly stubs, C headers.
- **Action**: For each target platform (OS/arch combination), the corresponding Bootlin GCC cross-compiler compiles C source.
- **Flags**: `-ffreestanding -nostdlib -nostartfiles -fno-builtin -fno-stack-protector -fPIC -ffunction-sections -fdata-sections -Os -Wall -Werror` plus architecture-specific flags.
- **Output**: Object files (`.o`) archived into `.a` per platform.

### Stage 3: Linking

- **Input**: Archive (`.a`) from Stage 2, custom linker script (`blob.ld`).
- **Action**: GCC links via genrule (not `cc_binary`, which injects `-Wl,-S`) with `-shared -nostdlib -nostartfiles -Wl,--whole-archive`.
- **Output**: A shared object (`.so`) with controlled section layout.
- **Sections**: `.text.pic_trampoline` (MIPS self-relocation), `.text.pic_entry` (entry point), `.text.pic_code` (helpers), `.text` (remaining), `.rodata`, `.got`, `.data`, `.bss`, `.config`.
- **Symbols**: `__blob_start`, `__blob_end`, `__config_start`, `__got_start`, `__got_end`.
- **Key**: `.symtab` is preserved for pyelftools to read at runtime.

### Stage 4: Runner Compilation

- **Input**: Test runner C source (`tests/runners/linux/runner.c`), per-architecture `_start` entry stubs.
- **Action**: Cross-compile the test runner for each target architecture using the same Bootlin toolchains. Linked as static freestanding binary via genrule.
- **Output**: One runner binary per OS/architecture combination.

### Stage 5: Staging

- **Input**: All `.so` blobs and runner binaries from Stages 3-4.
- **Action**: `tools/stage_blobs.py` (invoked via `picblobs build`) iterates over all platform configs, runs `bazel build --config={config}` for each, and copies outputs into the Python package tree.
- **Output directory structure**:
  ```
  python/picblobs/
    _blobs/{os}/{arch}/{blob_type}.so
    _runners/{os}/{arch}/runner
  ```

### Stage 6: Config Codegen (future)

- **Input**: C config header files (`config/*.h`).
- **Action**: pycparser-based codegen tool parses headers and emits Python `ctypes.Structure` subclasses.
- **Output**: `picblobs/_generated/configs.py`.

### Stage 7: Wheel Build

- **Input**: Complete Python package with staged blobs, runners, and generated code.
- **Action**: `uv build` produces a wheel.
- **Output**: `picblobs-X.Y.Z-py3-none-any.whl`.

## Parallelism

Stages 2-3 are per-platform and executed sequentially per platform config by `stage_blobs.py` (Bazel parallelizes within each config). Stage 4 runs alongside Stage 3 in the same Bazel invocation. Stage 6 is independent.

## Build Matrix Size

- 6 Linux platforms (x86_64, i686, aarch64, armv5_arm, mipsel32, mipsbe32)
- Future: 7 FreeBSD + 2 Windows = 16 total
- 1 blob type currently (hello); scales to 6 blob types per platform = 96 total
- 1 runner per platform = 6 runners currently
- Total artifacts per full build: blobs + runners + 1 wheel

## Derives From
- REQ-011
- REQ-012
- REQ-013
- REQ-017
