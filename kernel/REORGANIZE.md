# mbed/ Reorganization Plan

**Status**: PLANNED -- do not move files until tests pass.

## Goal

Extract kernel-related code from `mbed/` into a new top-level `kernel/` directory.
NaCl blobs stay in `mbed/` since they are not kernel-related.

## Current Structure

```
mbed/
  blobs/                          # Pre-existing NaCl blobs (NOT kernel-related)
    nacl_client.bin
    nacl_client_blob.h
    nacl_server.bin
    nacl_server_blob.h
  build_mbed.sh                   # Build script
  ebpf_kernel_loader.py           # eBPF kernel-context blob injection
  ebpf_kernel_mem.py              # eBPF kernel memory exploration
  ebpf_kernel_prog.py             # eBPF custom kernel programs
  ebpf_loader.py                  # eBPF userspace blob injection
  ebpf_loader_lab.md              # Lab guide
  kmod_loader/                    # Kernel module code
    Makefile
    build_examples.py
    examples/
      hello_ring0.S
      nop_sled.S
      who_am_i.S
    load_kmod.py
    pic_kblob.c
    pic_kmod.c
    portable_kmod.py
  vm_test/                        # VM test harness
    .gitignore
    vm_harness.py
```

## Proposed New Structure

```
kernel/                             # NEW top-level directory
  ebpf/                             # eBPF tools
    loader.py                        # <-- mbed/ebpf_loader.py
    kernel_loader.py                 # <-- mbed/ebpf_kernel_loader.py
    kernel_mem.py                    # <-- mbed/ebpf_kernel_mem.py
    kernel_prog.py                   # <-- mbed/ebpf_kernel_prog.py
  kmod/                              # Kernel module code
    Makefile                         # <-- mbed/kmod_loader/Makefile
    pic_kmod.c                       # <-- mbed/kmod_loader/pic_kmod.c
    pic_kblob.c                      # <-- mbed/kmod_loader/pic_kblob.c
    load_kmod.py                     # <-- mbed/kmod_loader/load_kmod.py
    portable_kmod.py                 # <-- mbed/kmod_loader/portable_kmod.py
    build_examples.py                # <-- mbed/kmod_loader/build_examples.py
    examples/                        # <-- mbed/kmod_loader/examples/
      nop_sled.S
      hello_ring0.S
      who_am_i.S
      kshell.c                       # NEW file (kernel reverse shell)
  vm/                                # VM test harness
    vm_harness.py                    # <-- mbed/vm_test/vm_harness.py
    .gitignore                       # <-- mbed/vm_test/.gitignore
  build.sh                           # <-- mbed/build_mbed.sh
  lab.md                             # <-- mbed/ebpf_loader_lab.md

mbed/                                # Kept for non-kernel artifacts
  blobs/                             # NaCl blobs stay here
    nacl_client.bin
    nacl_client_blob.h
    nacl_server.bin
    nacl_server_blob.h
```

## File Move Map

| Source (current)                         | Destination (new)                |
|------------------------------------------|----------------------------------|
| `mbed/ebpf_loader.py`                   | `kernel/ebpf/loader.py`         |
| `mbed/ebpf_kernel_loader.py`            | `kernel/ebpf/kernel_loader.py`  |
| `mbed/ebpf_kernel_mem.py`               | `kernel/ebpf/kernel_mem.py`     |
| `mbed/ebpf_kernel_prog.py`              | `kernel/ebpf/kernel_prog.py`    |
| `mbed/kmod_loader/Makefile`             | `kernel/kmod/Makefile`          |
| `mbed/kmod_loader/pic_kmod.c`           | `kernel/kmod/pic_kmod.c`        |
| `mbed/kmod_loader/pic_kblob.c`          | `kernel/kmod/pic_kblob.c`       |
| `mbed/kmod_loader/load_kmod.py`         | `kernel/kmod/load_kmod.py`      |
| `mbed/kmod_loader/portable_kmod.py`     | `kernel/kmod/portable_kmod.py`  |
| `mbed/kmod_loader/build_examples.py`    | `kernel/kmod/build_examples.py` |
| `mbed/kmod_loader/examples/nop_sled.S`  | `kernel/kmod/examples/nop_sled.S`  |
| `mbed/kmod_loader/examples/hello_ring0.S` | `kernel/kmod/examples/hello_ring0.S` |
| `mbed/kmod_loader/examples/who_am_i.S`  | `kernel/kmod/examples/who_am_i.S`  |
| `mbed/vm_test/vm_harness.py`            | `kernel/vm/vm_harness.py`       |
| `mbed/vm_test/.gitignore`               | `kernel/vm/.gitignore`          |
| `mbed/build_mbed.sh`                    | `kernel/build.sh`               |
| `mbed/ebpf_loader_lab.md`               | `kernel/lab.md`                 |

## New Files

| File                            | Description               |
|---------------------------------|---------------------------|
| `kernel/kmod/examples/kshell.c` | Kernel reverse shell blob |

## What Stays in mbed/

- `mbed/blobs/` -- NaCl client/server blobs and headers. Not kernel-related.

## Post-Move Cleanup

1. Remove emptied directories under `mbed/` (`kmod_loader/`, `vm_test/`).
2. Remove moved files from `mbed/` root (`ebpf_*.py`, `build_mbed.sh`, `ebpf_loader_lab.md`).
3. Update any internal imports or path references in the moved Python files.
4. Update `build.sh` paths if it references `mbed/` internally.
5. Check `kmod/Makefile` for hardcoded paths that assumed `mbed/kmod_loader/` layout.
6. Verify `vm_harness.py` path assumptions still hold.
7. Run tests before committing.

## Execution (when ready)

```bash
# Use git mv to preserve history
mkdir -p kernel/ebpf kernel/kmod/examples kernel/vm

git mv mbed/ebpf_loader.py          kernel/ebpf/loader.py
git mv mbed/ebpf_kernel_loader.py   kernel/ebpf/kernel_loader.py
git mv mbed/ebpf_kernel_mem.py      kernel/ebpf/kernel_mem.py
git mv mbed/ebpf_kernel_prog.py     kernel/ebpf/kernel_prog.py
git mv mbed/kmod_loader/Makefile    kernel/kmod/Makefile
git mv mbed/kmod_loader/pic_kmod.c  kernel/kmod/pic_kmod.c
git mv mbed/kmod_loader/pic_kblob.c kernel/kmod/pic_kblob.c
git mv mbed/kmod_loader/load_kmod.py      kernel/kmod/load_kmod.py
git mv mbed/kmod_loader/portable_kmod.py  kernel/kmod/portable_kmod.py
git mv mbed/kmod_loader/build_examples.py kernel/kmod/build_examples.py
git mv mbed/kmod_loader/examples/  kernel/kmod/examples/
git mv mbed/vm_test/vm_harness.py  kernel/vm/vm_harness.py
git mv mbed/vm_test/.gitignore     kernel/vm/.gitignore
git mv mbed/build_mbed.sh          kernel/build.sh
git mv mbed/ebpf_loader_lab.md     kernel/lab.md

# Clean up empty dirs (git rm handles this automatically)
rmdir mbed/kmod_loader mbed/vm_test 2>/dev/null || true
```
