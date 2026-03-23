# picblobs

Pre-compiled, position-independent code (PIC) blobs for loading and executing
arbitrary payloads on multiple operating systems and architectures. Eliminates
the need for hand-writing shellcode by providing tested, cross-platform PIC
stubs through a simple Python API.

## User Story

```text
As a cybersecurity developer, I am sick and tired of writing assembly and shellcode.
It would be amazing if Opus just solved the problem for me and yeeted it into pypi.
```

## Supported architectures

| Architecture | Endianness | Bits | Status |
|---|---|---|---|
| x86_64 | little | 64 | verified |
| i686 | little | 32 | verified |
| aarch64 | little | 64 | verified |
| armv5 (ARM mode) | little | 32 | verified |
| armv5 (Thumb mode) | little | 32 | verified |
| s390x (z13) | big | 64 | verified |
| mipsel32 | little | 32 | verified |
| mipsbe32 | big | 32 | verified |

## Prerequisites

- [Bazel 9](https://bazel.build/) (see `.bazelversion`)
- [QEMU user-static](https://www.qemu.org/) for cross-architecture testing
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for Python tooling

Toolchains are fetched automatically via [Bootlin](https://toolchains.bootlin.com/).

## Quick start

```bash
# Build hello blob + test runners for all Linux architectures
python tools/stage_blobs.py

# Verify everything works
python -m picblobs verify
```

## Building

The build system is Bazel 9 with bzlmod. Cross-compilation toolchains are
fetched from Bootlin automatically on first build.

### Build a single architecture

```bash
bazel build --config=linux_x86_64 //src/payload:hello
bazel build --config=linux_s390x //src/payload:hello
bazel build --config=linux_mipsel32 //src/payload:hello
```

### Build and stage all architectures

Staging copies the built `.so` blobs and test runner binaries into the Python
package tree at `python/picblobs/_blobs/` and `python/picblobs/_runners/`:

```bash
python tools/stage_blobs.py
```

Build specific targets or platforms:

```bash
python tools/stage_blobs.py --targets hello --configs linux:x86_64 linux:aarch64
```

### Available platform configs

All configs are defined in `.bazelrc`:

```
linux_x86_64  linux_i686  linux_aarch64  linux_armv5_arm  linux_armv5_thumb
linux_s390x  linux_mipsel32  linux_mipsbe32
```

## Running blobs

The `picblobs` CLI operates on blobs already built into the package. It has no
knowledge of the build system.

```bash
# Run hello on x86_64 (native)
python -m picblobs run hello

# Run hello on a specific architecture (via QEMU)
python -m picblobs run hello linux:aarch64
python -m picblobs run hello linux:s390x

# Run a .so file directly (for development)
python -m picblobs run --so bazel-bin/src/payload/hello.so linux:mipsel32

# Verify all architectures
python -m picblobs verify

# Verify specific architectures
python -m picblobs verify --arch x86_64 --arch mipsel32

# List all blobs in the package
python -m picblobs list

# Show blob metadata
python -m picblobs info hello linux:x86_64
```

## Testing

```bash
# Run the full test suite (60 tests)
python -m pytest python/tests/ -v

# Run only the sync/consistency tests
python -m pytest python/tests/test_sync.py -v

# Run tests filtered by architecture
python -m picblobs test --arch x86_64
```

## Writing a blob

A blob is a freestanding C program that runs at any address. Include the
target OS header first, then the syscall wrappers you need:

```c
#include "picblobs/os/linux.h"
#include "picblobs/section.h"
#include "picblobs/reloc.h"
#include "picblobs/sys/write.h"
#include "picblobs/sys/exit_group.h"

PIC_RODATA
static const char msg[] = "Hello, world!\n";

PIC_ENTRY
void _start(void)
{
	PIC_SELF_RELOCATE();
	pic_write(1, msg, sizeof(msg) - 1);
	pic_exit_group(0);
}
```

Each `sys/*.h` header is a self-contained module: it includes the syscall
numbers for every supported OS/architecture combination, the constants,
and the wrapper function. No central header needed.

Drop the `.c` file into `src/payload/`, run `python tools/generate.py`, and
it will be picked up automatically.

## Code generation

Most boilerplate files are generated from the canonical registry at
`tools/registry.py`. After modifying the registry, regenerate:

```bash
python tools/generate.py
```

This generates:
- `src/include/picblobs/arch.h` (architecture traits)
- `src/include/picblobs/syscall.h` (dispatcher to per-arch primitives)
- `src/include/picblobs/picblobs.h` (convenience header)
- `src/include/picblobs/sys/*.h` (per-syscall modules with numbers + wrappers)
- `platforms/BUILD.bazel`, `toolchains/BUILD.bazel`, `.bazelrc` (Bazel config)
- `src/payload/BUILD.bazel` (auto-discovered blob targets)
- `tests/runners/*/runner.c` (dispatcher to per-arch `_start` stubs)

To verify generated files are up to date:

```bash
python tools/generate.py --check
```

## Adding a new architecture

1. Add an `Architecture` entry to `tools/registry.py`
2. Add syscall numbers to `SYSCALL_NUMBERS["linux"]` in `registry.py`
3. Create `src/include/picblobs/syscall/{arch}.h` with the inline asm primitive
4. Create `tests/runners/linux/start/{arch}.h` with the `_start` stub
5. Add a `bootlin.toolchain()` block to `MODULE.bazel`
6. Run `python tools/generate.py`
7. Run `python -m pytest python/tests/test_sync.py -v` (catches anything missed)
8. Build, stage, verify:
   ```bash
   bazel build --config=linux_{arch} //src/payload:hello //tests/runners/linux:runner
   python tools/stage_blobs.py --configs linux:{arch}
   python -m picblobs verify --arch {arch}
   ```

## Adding a new syscall

1. Add the number to every architecture's table in `SYSCALL_NUMBERS` in `registry.py`
2. Add a `SyscallDef` entry to `SYSCALL_DEFS` in `registry.py`
3. Run `python tools/generate.py`

The generated `sys/{name}.h` will contain the numbers, OS guards, and wrapper.

## Formatting and linting

### Formatting

C code follows Linux kernel style (`.clang-format`). Python uses ruff defaults.

```bash
python tools/fmt.py            # format all C and Python files in place
python tools/fmt.py --check    # verify formatting without modifying (CI)
```

`fmt.py` runs clang-format on all `.c`/`.h` files under `src/` and `tests/`,
and ruff on all `.py` files under `python/` and `tools/`. Generated files are
included — the generator produces formatted output, so the two are idempotent.

### Linting

```bash
bazel build --config=lint //src/... //tests/...   # clang-tidy via aspect
```

The lint aspect runs clang-tidy on every `cc_library` target in the build graph.
Configuration is in `.clang-tidy`. Warnings are errors.

### CI checks

```bash
bazel test //tools:format_check     # verify formatting
bazel test //tools:generate_check   # verify generated files are fresh
bazel build --config=lint //src/... # clang-tidy
```

Or all at once:

```bash
bazel test //tools:all && bazel build --config=lint //src/... //tests/...
```

## Project structure

```
tools/
  registry.py          # canonical platform/syscall registry
  generate.py          # generates all derived files
  stage_blobs.py       # copies bazel outputs into Python package tree
  fmt.py               # format all C and Python files
  fmt_check.sh         # Bazel test wrapper for format check
  generate_check.sh    # Bazel test wrapper for codegen freshness

src/
  include/picblobs/
    arch.h             # [generated] architecture traits
    types.h            # portable types (no libc)
    syscall.h          # [generated] dispatcher to per-arch asm
    syscall/           # per-arch syscall primitives (hand-written)
    section.h          # section placement macros + MIPS trampoline
    reloc.h            # MIPS GOT self-relocation
    picblobs.h         # [generated] convenience header
    os/                # OS selection headers
    sys/               # [generated] per-syscall modules
  payload/             # blob source files
  linker/blob.ld       # custom linker script

tests/runners/linux/
  runner.c             # [generated] test runner dispatcher
  start/               # per-arch _start stubs (hand-written)

python/picblobs/
  __init__.py          # public API: get_blob(), list_blobs()
  _extractor.py        # runtime ELF extraction via pyelftools
  runner.py            # QEMU execution orchestration
  cli.py               # CLI: list, info, extract, run, verify, test
  _blobs/              # staged .so files (built by Bazel)
  _runners/            # staged runner binaries (built by Bazel)
```
