# picblobs

Position-independent code blobs for multiple OS/arch targets. Bazel 9 + bzlmod build system with Bootlin cross-compilation toolchains.

**Version**: 0.1.0 | **License**: MIT | **Python**: 3.10+

## Dev setup

```bash
source sourceme
```

## Building

Target = what to build. Config = how to build it. One aggregate target, orthogonal configs.

```bash
# Single platform
bazel build //release:full --config=linux_x86_64
bazel build //release:full --config=linux_x86_64 --config=debug

# All platforms + stage into Python wheel tree
./buildall
```

## Testing

```bash
python -m pytest python/tests/ -v
python -m picblobs verify
```

## Code generation

Most boilerplate is generated from `tools/registry.py`. After modifying the registry:

```bash
python tools/generate.py
python tools/generate.py --check   # verify freshness (CI)
```

## Formatting and linting

```bash
python tools/fmt.py                # format C + Python
bazel build --config=lint //src/... //tests/...   # clang-tidy
```

## Key conventions

- Blobs are freestanding C (`-ffreestanding -nostdlib -fPIC -Os`). No libc.
- Platform configs are generated — do not hand-edit the block between `BEGIN/END GENERATED PLATFORM CONFIGS` in `.bazelrc`.
- Debug/release are orthogonal `--config=debug` / `--config=release` flags, not separate targets.
- Toolchain SHA256 hashes in `MODULE.bazel` must be pinned. Never leave them empty.
- `hello_windows` only builds for `windows:*` platform configs (TEB support is arch-gated).
- Windows test runner (`tests/runners/windows/runner.c`) is hand-written (not generated) — it's a Linux binary that mocks TEB/PEB. Build with a Linux config: `bazel build --config=linux_x86_64 //tests/runners/windows:runner`.
- FreeBSD test runner has WIP compile errors and is commented out of `//release:full`.

---

## Python API Reference

### Core Module: `picblobs`

#### Functions

**`get_blob(blob_type: str, target_os: str, target_arch: str) -> BlobData`**
- Load and extract a blob by type, OS, and architecture.
- Results are cached (LRU cache, max 64 entries) — repeated calls return the same BlobData instance.
- **Args**:
  - `blob_type`: Blob type identifier (e.g., "hello", "alloc_jump", "stager_tcp")
  - `target_os`: Target OS (e.g., "linux", "freebsd", "windows")
  - `target_arch`: Target architecture (e.g., "x86_64", "aarch64")
- **Returns**: `BlobData` with extracted code bytes and metadata
- **Raises**: `FileNotFoundError` if no blob exists for the given combination

**`list_blobs() -> list[tuple[str, str, str]]`**
- Return all available (blob_type, target_os, target_arch) tuples in the package
- Dynamically discovers from filesystem: `picblobs/_blobs/{os}/{arch}/{type}.so`
- **Returns**: List of tuples (blob_type, target_os, target_arch), sorted alphabetically

**`clear_cache() -> None`**
- Clear the blob extraction cache
- Call after rebuilding .so files in development

#### Classes

**`BlobData` (dataclass, frozen)**
- Extracted blob bytes and metadata from a .so file
- **Attributes**:
  - `code: bytes` — Flat code bytes from `__blob_start` to `__blob_end`
  - `config_offset: int` — Offset of `__config_start` relative to `__blob_start`
  - `entry_offset: int` — Offset of the entry point (normally 0)
  - `blob_type: str` — Blob type identifier (e.g., 'alloc_jump')
  - `target_os: str` — Target operating system (e.g., 'linux')
  - `target_arch: str` — Target architecture (e.g., 'x86_64')
  - `sha256: str` — SHA-256 hex digest of the code bytes
  - `sections: dict[str, tuple[int, int]]` — Section name → (offset_from_blob_start, size)

#### Module Constants

- `__version__: str` — "0.1.0"
- `__all__: list[str]` — Public API exports: ["get_blob", "list_blobs", "BlobData", "extract", "clear_cache"]

---

### Extractor Module: `picblobs._extractor`

#### Functions

**`extract(so_path: str | Path, blob_type: str = "", target_os: str = "", target_arch: str = "") -> BlobData`**
- Extract flat blob bytes and metadata from a .so file.
- **Args**:
  - `so_path`: Path to the .so blob file
  - `blob_type`: Blob type override. If empty, derived from filename (stem)
  - `target_os`: Target OS override. If empty, derived from path (parts[-3])
  - `target_arch`: Target arch override. If empty, derived from path (parts[-2])
- **Returns**: `BlobData` with extracted code bytes and metadata
- **Raises**:
  - `ValueError`: If required symbols (`__blob_start`, `__blob_end`, `__config_start`) or .symtab section is missing
  - `FileNotFoundError`: If so_path does not exist
- **Expected layout**: `.../_blobs/{os}/{arch}/{blob_type}.so`

#### Implementation Details

- Uses `pyelftools` to parse ELF files
- Reads `__blob_start` and `__blob_end` symbols from `.symtab`
- Extracts allocated sections (SHF_ALLOC flag) between blob boundaries
- Handles both SHT_PROGBITS (copies data) and SHT_NOBITS (fills with zeros for .bss)
- Single-pass collection of sections with metadata

---

### Runner Module: `picblobs.runner`

#### Functions

**`find_qemu(arch: str) -> Path`**
- Locate the QEMU user-static binary for an architecture
- **Args**: `arch` — Architecture name (e.g., "x86_64", "aarch64")
- **Returns**: Path to the QEMU binary
- **Raises**: `FileNotFoundError` if QEMU binary not found on PATH

**`find_runner(runner_type: str, arch: str = "", search_paths: list[Path] | None = None) -> Path`**
- Locate a compiled C test runner binary
- **Search order**:
  1. Embedded in package: `picblobs/_runners/{runner_type}/{arch}/runner`
  2. Bazel build tree: `bazel-bin/tests/runners/{runner_type}/runner.bin` or `runner`
- **Args**:
  - `runner_type`: One of "linux", "freebsd", "windows"
  - `arch`: Target architecture (e.g., "x86_64", "aarch64")
  - `search_paths`: Override search directories (defaults to Bazel output tree)
- **Returns**: Path to the runner binary
- **Raises**: `FileNotFoundError` if runner binary not found

**`prepare_blob(blob: BlobData, config: bytes = b"", output_dir: Path | None = None) -> Path`**
- Write blob code + config to a temp file
- **Args**:
  - `blob`: Extracted blob data
  - `config`: Serialized config struct to append at config_offset
  - `output_dir`: Directory for the temp file. Uses system temp if None
- **Returns**: Path to the prepared blob binary file
- **Behavior**: Creates temp file named `{blob_type}_{os}_{arch}.bin` with code + config merged

**`run_blob(blob: BlobData, config: bytes = b"", runner_type: str = "", runner_path: Path | None = None, timeout: float = 30.0, debug: bool = False, dry_run: bool = False) -> RunResult`**
- Prepare and execute a blob under QEMU
- **Args**:
  - `blob`: Extracted blob data
  - `config`: Serialized config struct
  - `runner_type`: Test runner type ("linux", "freebsd", "windows"). Defaults to blob.target_os
  - `runner_path`: Explicit path to the runner binary. Auto-discovered if None
  - `timeout`: Execution timeout in seconds (default 30.0)
  - `debug`: Print verbose info (paths, command, timing). Keep temp files
  - `dry_run`: Build command but don't execute
- **Returns**: `RunResult` with stdout, stderr, exit code, and duration
- **Raises**:
  - `FileNotFoundError`: If QEMU or runner binary not found
  - `subprocess.TimeoutExpired`: If execution exceeds timeout

**`run_so(so_path: str | Path, config: bytes = b"", runner_type: str = "", runner_path: Path | None = None, timeout: float = 30.0, debug: bool = False, dry_run: bool = False) -> RunResult`**
- Extract a .so and run it in one call (convenience for development)
- **Args**: Same as `run_blob` (but takes .so path instead of BlobData)
- **Returns**: `RunResult`

**`is_arch_skip_rosetta(arch: str) -> bool`**
- Check if an architecture should be skipped under Rosetta 2 (Apple Silicon Docker Desktop)
- **Background**: QEMU MIPS user-static crashes when running PIC blobs with GOT self-relocation under Rosetta
- **Args**: `arch` — Architecture name
- **Returns**: True if arch is in {"mipsel32", "mipsbe32"} AND running under Rosetta

**`is_rosetta() -> bool`**
- Detect Rosetta 2 x86_64 emulation (cached)
- Checks `/proc/cpuinfo` for `vendor_id : VirtualApple`

#### Classes

**`RunResult` (dataclass, frozen)**
- Result of running a blob under QEMU
- **Attributes**:
  - `stdout: bytes` — Standard output from the blob execution
  - `stderr: bytes` — Standard error output
  - `exit_code: int` — Process exit code
  - `duration_s: float` — Wall-clock execution time in seconds
  - `command: list[str]` — Full command line executed
  - `blob_file: str` — Path to temp blob file (empty for dry_run)

---

### Debug Module: `picblobs.debug`

Debug CLI for development (not shipped in wheel). Extends main CLI with disassembly commands.

#### Functions

**`cmd_disasm(args: argparse.Namespace) -> int`**
- Disassemble a single function or list function symbols from a debug .so
- **Arguments**:
  - `type`: Blob type
  - `target`: os:arch (e.g., "linux:x86_64")
  - `-f, --function`: Function name to disassemble (without arg, lists all symbols)
  - `--so`: Direct path to .so file
- **Behavior**:
  - Searches debug blob directory first: `{PROJECT_ROOT}/debug/{os}/{arch}/{type}.so`
  - Requires DWARF debug info for source interleaving
  - Uses cross-toolchain objdump found via `_objdump.find_objdump()`

**`cmd_debug_listing(args: argparse.Namespace) -> int`**
- Full disassembly listing, preferring debug .so files
- Falls back to release .so if debug not available
- Returns disassembly output to stdout

---

### Disassembly Module: `picblobs._objdump`

#### Functions

**`find_objdump(arch: str) -> str`**
- Find the correct objdump binary for the given architecture
- **Search order**:
  1. Bazel-provisioned Bootlin toolchain in output tree
  2. System-installed cross-toolchain binaries (via PATH)
- **Args**: `arch` — Architecture name
- **Returns**: Path to objdump binary
- **Raises**: `FileNotFoundError` if no suitable objdump found
- **Supported architectures**: x86_64, i686, aarch64, armv5_arm, armv5_thumb, mipsel32, mipsbe32, s390x

**`list_symbols(so_path: str, objdump: str) -> list[tuple[str, str, str]]`**
- List function symbols from a .so file
- **Args**:
  - `so_path`: Path to .so file
  - `objdump`: Path to objdump binary
- **Returns**: List of (address, size, name) tuples for FUNC symbols
- Uses `objdump -t` (symbol table)

**`disassemble_function(so_path: str, objdump: str, function: str, source: bool = True) -> str`**
- Disassemble a single function from a .so file
- **Args**:
  - `so_path`: Path to .so file
  - `objdump`: Path to objdump binary
  - `function`: Function name to disassemble
  - `source`: If True, interleave source lines (-S). Requires debug symbols
- **Returns**: Disassembly output as a string
- **Raises**: `RuntimeError` if objdump fails or function not found

**`disassemble_full(so_path: str, objdump: str, source: bool = True) -> str`**
- Produce a full disassembly listing of a .so file
- **Args**:
  - `so_path`: Path to .so file
  - `objdump`: Path to objdump binary
  - `source`: If True, interleave source lines (-S)
- **Returns**: Full disassembly output as a string
- **Raises**: `RuntimeError` if objdump fails

**`has_debug_info(so_path: str, objdump: str) -> bool`**
- Check whether a .so file contains DWARF debug info
- Checks for `.debug_info` section via `objdump -h`

---

### QEMU Module: `picblobs._qemu`

#### Constants

**`QEMU_BINARIES: dict[str, str]`**
- Mapping of architecture names to QEMU user-static binary names
- Derived from `tools/registry.py` or fallback hardcoded values
- Example:
  ```python
  {
      "x86_64": "qemu-x86_64-static",
      "aarch64": "qemu-aarch64-static",
      "mipsel32": "qemu-mipsel-static",
      # ...
  }
  ```

---

## Command-Line Interface (CLI)

Accessible via `python -m picblobs` or `picblobs` entry point.

### Main Commands

#### `picblobs list`
List all blobs in the package
```bash
picblobs list
```
**Output**: Formatted table of (BLOB TYPE, OS, ARCH)

#### `picblobs info [type] [target]`
Show blob metadata
```bash
picblobs info hello linux:x86_64
picblobs info --so path/to/blob.so linux:x86_64
```
**Arguments**:
- `type`: Blob type (e.g., "hello") — required unless `--so` provided
- `target`: os:arch (default: "linux:x86_64")
- `--so`: Direct path to .so file (overrides type/target for file, but target still needed)

**Output**: Blob metadata including code size, config offset, entry offset, SHA-256, and sections

#### `picblobs extract type target -o OUTPUT [--config-hex HEX]`
Extract flat blob binary to a file
```bash
picblobs extract hello linux:x86_64 -o /tmp/hello.bin
picblobs extract hello linux:x86_64 -o /tmp/hello.bin --config-hex "0102030405"
picblobs extract --so path/to/hello.so -o output.bin --config-hex "..."
```
**Arguments**:
- `type`: Blob type — required unless `--so` provided
- `target`: os:arch (default: "linux:x86_64")
- `-o, --output`: Output file path (required)
- `--so`: Direct path to .so file
- `--config-hex`: Config struct as hex string (injected at config_offset)

**Output**: Success message with byte count

#### `picblobs run [type] [target] [--config-hex HEX | --payload FILE] [options]`
Run a single blob under QEMU
```bash
picblobs run hello                          # linux:x86_64 default
picblobs run hello linux:aarch64             # cross-arch
picblobs run hello linux:x86_64 --debug      # verbose output
picblobs run --so path/to/hello.so           # direct .so file
picblobs run hello --config-hex "0102030405"
picblobs run hello --payload /tmp/config.bin
```
**Arguments**:
- `type`: Blob type — required unless `--so` provided
- `target`: os:arch (default: "linux:x86_64")
- `--so`: Direct path to .so file
- `--config-hex`: Config struct as hex string
- `--payload`: Read config from file
- `--runner-type`: Runner type override ("linux", "freebsd", "windows")
- `--runner-path`: Explicit path to runner binary
- `--timeout`: Timeout in seconds (default: 30.0)
- `--debug`: Verbose output, keep temp files
- `--dry-run`: Print command without executing

**Output**: Blob stdout/stderr passed through, exit code propagated

#### `picblobs verify [--type TYPE] [--os OS] [--arch ARCH] [--timeout TIMEOUT]`
Smoke test: run a blob on every architecture available in the package
```bash
picblobs verify                                # hello on all linux arches
picblobs verify --arch x86_64 --arch mipsel32  # specific arches
picblobs verify --type alloc_jump               # different blob
picblobs verify --os freebsd                    # freebsd arches
```
**Arguments**:
- `--type`: Blob type (default: "hello")
- `--os`: Target OS (default: "linux")
- `--arch`: Architecture (repeatable, default: all available)
- `--timeout`: Per-blob timeout in seconds (default: 30.0)

**Output**: Results summary with pass/fail counts

#### `picblobs listing [type] [target] [--so SO]`
Full disassembly listing of a blob .so via cross-toolchain objdump
```bash
picblobs listing hello linux:x86_64
picblobs listing --so path/to/hello.so linux:aarch64
```
**Arguments**:
- `type`: Blob type — required unless `--so` provided
- `target`: os:arch (default: "linux:x86_64")
- `--so`: Direct path to .so file

**Output**: Disassembly to stdout (may include source lines if debug info present)

#### `picblobs test [-v] [-k FILTER] [--os OS] [--arch ARCH] [--type TYPE] [pytest_args ...]`
Run pytest test suite with optional filtering
```bash
picblobs test                                  # run all tests
picblobs test -v                               # verbose
picblobs test -k test_extract                  # filter by name
picblobs test --os linux --arch x86_64         # filter by target
```
**Arguments**:
- `-v, --verbose`: Verbose pytest output
- `-k, --filter`: pytest -k expression
- `--os`: Filter by OS (sets env var PICBLOBS_TEST_OS)
- `--arch`: Filter by architecture (sets env var PICBLOBS_TEST_ARCH)
- `--type`: Filter by blob type (sets env var PICBLOBS_TEST_TYPE)
- `pytest_args`: Additional pytest arguments

---

## Registry: Platform & Architecture Definitions

Located in `/tools/registry.py` — **single source of truth** for all platforms, architectures, and syscall numbers.

### Supported Platforms

#### Operating Systems

| OS | Architectures | Runner Type |
|---|---|---|
| linux | x86_64, i686, aarch64, armv5_arm, armv5_thumb, s390x, mipsel32, mipsbe32 | linux |
| freebsd | x86_64, i686, aarch64, armv5_arm, armv5_thumb, mipsel32, mipsbe32 | freebsd |
| windows | x86_64, i686, aarch64 | windows |

#### Supported Architectures

| Name | GCC Define | QEMU Binary | Bootlin Arch | 32-bit | Traits |
|---|---|---|---|---|---|
| x86_64 | `__x86_64__` | qemu-x86_64-static | x86-64 | No | — |
| i686 | `__i386__` | qemu-i386-static | x86-i686 | Yes | uses_mmap2 |
| aarch64 | `__aarch64__` | qemu-aarch64-static | aarch64 | No | openat_only |
| armv5_arm | `__arm__` | qemu-arm-static | armv5-eabi | Yes | uses_mmap2 |
| armv5_thumb | `__arm__` | qemu-arm-static | armv5-eabi | Yes | uses_mmap2 |
| s390x | `__s390x__` | qemu-s390x-static | s390x-z13 | No | uses_old_mmap |
| mipsel32 | `__mips__` | qemu-mipsel-static | mips32el | Yes | uses_mmap2, needs_got_reloc, needs_trampoline |
| mipsbe32 | `__mips__` | qemu-mips-static | mips32 | Yes | uses_mmap2, needs_got_reloc, needs_trampoline |

### Architecture Traits

Boolean flags controlling per-architecture decisions:
- `uses_mmap2`: Uses mmap2 syscall with page-unit offset
- `uses_old_mmap`: Uses old_mmap (args via struct pointer, not registers)
- `openat_only`: No legacy open syscall (use openat)
- `needs_got_reloc`: Needs GOT self-relocation (PIC_SELF_RELOCATE)
- `needs_trampoline`: Needs entry trampoline for PIC setup
- `is_32bit`: 32-bit architecture (affects lseek, etc.)

### Bazel Configurations

Platform configs in `.bazelrc`:
```
build:linux_x86_64      --platforms=//platforms:linux_x86_64
build:linux_aarch64     --platforms=//platforms:linux_aarch64
# ... etc for all platforms
```

Use as: `bazel build --config=linux_x86_64 //...`

### Syscall Numbers

Defined in `SYSCALL_NUMBERS` dict with OS/arch granularity:
```
SYSCALL_NUMBERS[os][gcc_define][syscall_name] = number
```

**Supported syscalls**: read, write, open, openat, close, lseek, llseek, mmap, mprotect, munmap, socket, connect, accept, bind, listen, setsockopt, dup2, pipe, fstat, exit, exit_group

---

## Tools & Build Scripts

### `tools/generate.py`

Regenerate all derived files from the canonical registry (tools/registry.py)

```bash
python tools/generate.py              # generate all
python tools/generate.py --check      # exit 1 if any file is stale
```

**Generated files**:
- C headers:
  - `src/include/picblobs/arch.h` — architecture trait flags
  - `src/include/picblobs/syscall.h` — dispatcher to per-arch syscall files
  - `src/include/picblobs/picblobs.h` — master include for blob authors
  - `src/include/picblobs/sys/{os}/nr.h` — syscall numbers per OS
  - `src/include/picblobs/sys/{name}.h` — per-syscall wrapper functions
  
- Bazel files:
  - `platforms/BUILD.bazel` — platform definitions
  - `toolchains/BUILD.bazel` — toolchain configurations
  
- Config:
  - `.bazelrc` — platform config blocks (between markers)
  
- C test runners:
  - `tests/runners/{os}/runner.c` — per-OS runner dispatcher
  - `tests/runners/{os}/start/{arch}.h` — per-arch entry stubs

**Key functions**:
- `_gen_arch_h()` — Generates PIC_ARCH_* trait macros per architecture
- `_gen_syscall_h()` — Generates dispatcher to per-arch syscall implementations
- `_gen_picblobs_h()` — Generates master include with all syscall wrappers

### `tools/fmt.py`

Format all project source files

```bash
python tools/fmt.py            # format in place
python tools/fmt.py --check    # exit 1 if anything would change (for CI)
```

**Formatters**:
- **C/H files**: clang-format (via `.clang-format` config)
- **Python files**: ruff format

**Search roots**:
- C: `src/`, `tests/`
- Python: `python/picblobs/`, `tools/`, `python/tests/`

**Exclusions**: bazel-*, .venv, __pycache__, .cache, node_modules

### `tools/stage_blobs.py`

Build and stage .so blobs and test runners into the Python package tree

```bash
python tools/stage_blobs.py                       # build + stage all
python tools/stage_blobs.py --targets hello        # one blob type
python tools/stage_blobs.py --configs linux:x86_64 # one platform
python tools/stage_blobs.py --no-runners           # blobs only
python tools/stage_blobs.py --debug                # debug builds
```

**Key functions**:
- `discover_blob_targets()` — Parse `src/payload/BUILD.bazel` for pic_blob() rules
- `bazel_build(configs, labels)` — Run Bazel build for platform configs + labels
- `stage_file(src, dest, executable)` — Copy file with permission handling
- `find_bazel_output(label, extension)` — Convert Bazel label to bazel-bin path
- `build_and_stage(targets, configs, no_runners, debug)` — Main workflow

**Output directories**:
- Release: `python/picblobs/_blobs/{os}/{arch}/{name}.so`
- Debug: `debug/{os}/{arch}/{name}.so`
- Runners: `python/picblobs/_runners/{runner_type}/{arch}/runner`

**Bazel labels**:
- Blobs: `//src/payload:{name}` → `.so` in bazel-bin
- Runners: `//tests/runners/{runner_type}:runner` → `.bin` in bazel-bin

### `buildall` (shell script)

Convenience wrapper around `tools/stage_blobs.py`

```bash
./buildall                  # build + stage all platforms
./buildall --no-stage       # build only (passes to stage_blobs.py)
./buildall --debug          # build debug variants
```

---

## Bazel Configuration (`.bazelrc`)

### Build Settings
```
build --incompatible_enable_cc_toolchain_resolution
build --sandbox_default_allow_network=false
build --stamp=false
```

### Platform Configs (generated)
```
build:linux_x86_64      --platforms=//platforms:linux_x86_64
build:linux_aarch64     --platforms=//platforms:linux_aarch64
# ... all platform combinations
```

### Build Mode Configs
```
build:debug   --copt=-g --copt=-DPIC_LOG_ENABLE --strip=never
build:release --strip=always
```

### Usage
```bash
bazel build --config=linux_x86_64 //src/payload:hello
bazel build --config=linux_x86_64 --config=debug //src/payload:hello
bazel build //release:full --config=linux_x86_64
```

**Composable**: Platform + build mode can be combined (e.g., `--config=linux_x86_64 --config=debug`)

---

## Package Metadata

### `pyproject.toml`

```toml
[project]
name = "picblobs"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["pyelftools>=0.31"]

[project.scripts]
picblobs = "picblobs.cli:main"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pycparser>=2.22"]
```

### Package Contents

```
python/picblobs/
├── __init__.py              # Public API: get_blob, list_blobs, BlobData
├── __main__.py              # CLI entry point
├── cli.py                   # Main CLI with 7 subcommands
├── debug.py                 # Debug CLI (development only)
├── runner.py                # QEMU execution + runner discovery
├── _extractor.py            # ELF extraction via pyelftools
├── _qemu.py                 # QEMU binary name mapping
├── _objdump.py              # Disassembly via cross-toolchain objdump
├── _blobs/                  # .so files staged by build system
│   ├── linux/x86_64/hello.so
│   ├── linux/aarch64/hello.so
│   └── ...
├── _runners/                # Cross-compiled test runners
│   ├── linux/x86_64/runner
│   └── ...
└── _generated/              # Auto-generated files (C headers, etc.)
```

### Wheel Contents

The wheel includes:
- All Python modules
- `_blobs/` directory (blobs staged by `stage_blobs.py`)
- `_runners/` directory (runners staged by `stage_blobs.py`)
- `_generated/` directory (derived headers)

---

## Workflow Examples

### List Available Blobs
```python
from picblobs import list_blobs

for blob_type, os_name, arch in list_blobs():
    print(f"{blob_type} {os_name}:{arch}")
```

### Load and Extract a Blob
```python
from picblobs import get_blob

blob = get_blob("hello", "linux", "x86_64")
print(f"Code size: {len(blob.code)} bytes")
print(f"Config offset: {blob.config_offset}")
print(f"SHA-256: {blob.sha256}")
```

### Run a Blob with Config
```python
from picblobs import get_blob
from picblobs.runner import run_blob

blob = get_blob("hello", "linux", "aarch64")
config = bytes([0x01, 0x02, 0x03, 0x04])

result = run_blob(blob, config=config, timeout=10.0)
print(result.stdout.decode())
print(f"Exit code: {result.exit_code}")
```

### CLI: Smoke Test
```bash
source sourceme && python -m picblobs verify
```

### CLI: Extract to File
```bash
python -m picblobs extract hello linux:x86_64 -o /tmp/blob.bin
```

### CLI: Run with Hex Config
```bash
python -m picblobs run hello linux:aarch64 --config-hex "0102030405"
```

### Build & Stage (Development)
```bash
# Build all platforms
./buildall

# Build specific target + platform
python tools/stage_blobs.py --targets hello --configs linux:x86_64

# Build debug variants (with -g and PIC_LOG)
python tools/stage_blobs.py --debug --configs linux:x86_64
```

---

## Architecture Reference

### Symbol Conventions (from linker script)

- `__blob_start` — Start of executable code/data region
- `__blob_end` — End of code region (config follows)
- `__config_start` — Start of config struct region
- `__got_start`, `__got_end` — Global Offset Table boundaries (MIPS)

### Section Layout

Typical memory layout (from linker script):
```
.text → .rodata → .data → .bss → .config
```

### Config Struct

Blobs can have an optional config struct at `config_offset` within the code:
- Fixed offset determined at link time
- Extracted via `BlobData.config_offset`
- Injected via `--config-hex` or `--payload` flags
- Blob reads from this offset at runtime

---

## Testing

Run the test suite:
```bash
source sourceme
python -m picblobs test                    # all tests
python -m picblobs test -v -k test_extract # specific test
python -m picblobs test --os linux --arch x86_64 # filter
```

**Test environment variables** (set automatically by CLI):
- `PICBLOBS_TEST_OS` — Filter by OS
- `PICBLOBS_TEST_ARCH` — Filter by architecture
- `PICBLOBS_TEST_TYPE` — Filter by blob type

---

## Troubleshooting

### "No blob for X/Y/Z"
- Run `python -m picblobs list` to see available combinations
- Ensure blobs are staged: `python tools/stage_blobs.py`

### QEMU not found
- Install: `apt install qemu-user-static` (Linux) or `brew install qemu` (macOS)
- Verify: `which qemu-x86_64-static`

### Runner binary not found
- Build and stage runners: `python tools/stage_blobs.py` (not `--no-runners`)
- Check: `ls python/picblobs/_runners/linux/x86_64/runner`

### Objdump not found (for disassembly)
- Install cross-toolchain: `apt install binutils-{arm,aarch64,mips}-linux-gnu`
- Or build with Bazel: toolchains are fetched from Bootlin automatically

### Rosetta 2 QEMU crashes (Apple Silicon)
- MIPS blobs may fail under Rosetta due to GOT self-relocation incompatibility
- Use `is_arch_skip_rosetta()` to detect and skip these architectures

---

## Dependencies

### Runtime
- **pyelftools** ≥0.31 — ELF parsing and extraction

### Build System
- **Bazel** 9.x (see `.bazelversion`)
- **Python** 3.10+
- **uv** (recommended) or pip/venv

### Development
- **pytest** ≥8.0 — Test framework
- **ruff** — Python formatter/linter
- **clang-format** — C code formatter
- **QEMU** user-static — Cross-architecture execution
- **Bootlin cross-toolchains** — Fetched automatically via Bazel

