# MOD-004: Syscall Abstraction Layer Architecture

## Status
Accepted

## Description

This model describes the layered architecture of the syscall abstraction system for Linux and FreeBSD targets. The architecture has three layers: the assembly primitive, the syscall number tables, and the C wrapper headers/sources.

## Layer Diagram

```
+============================================================+
| Layer 3: C Syscall Wrapper Headers                         |
|                                                            |
|   include/linux/sys/mman.h    -> mmap(), mprotect(), ...  |
|   include/linux/sys/socket.h  -> socket(), connect(), ... |
|   include/linux/sys/stat.h    -> stat(), fstat(), ...     |
|   include/freebsd/sys/mman.h  -> mmap(), mprotect(), ... |
|   include/freebsd/sys/socket.h -> socket(), connect(),...  |
|   ...                                                      |
|                                                            |
|   Each function: accepts typed args, passes syscall number |
|   and args to the Layer 1 primitive.                       |
|   Implemented as static inline functions or thin source    |
|   files compiled with -ffunction-sections.                 |
+============================================================+
                          |
                          | calls
                          v
+============================================================+
| Layer 2: Syscall Number Tables                             |
|                                                            |
|   include/linux/x86_64/syscall_numbers.h                   |
|     #define __NR_mmap 9                                    |
|     #define __NR_mprotect 10                               |
|     ...                                                    |
|                                                            |
|   include/linux/aarch64/syscall_numbers.h                  |
|     #define __NR_mmap 222                                  |
|     ...                                                    |
|                                                            |
|   include/freebsd/common/syscall_numbers.h                 |
|     #define SYS_mmap 477                                   |
|     ...                                                    |
|                                                            |
|   One table per OS/arch (Linux) or per OS (FreeBSD).       |
|   Derived from kernel sources, version-pinned.             |
+============================================================+
                          |
                          | #define constants used by
                          v
+============================================================+
| Layer 1: Assembly Syscall Primitive                        |
|                                                            |
|   src/arch/x86_64/syscall.S                                |
|     long raw_syscall(long nr, long a1, ..., long a6);     |
|                                                            |
|   src/arch/i686/syscall.S                                  |
|   src/arch/aarch64/syscall.S                               |
|   src/arch/armv5/syscall.S     (ARM mode)                  |
|   src/arch/armv5/syscall_thumb.S (Thumb mode)              |
|   src/arch/mipsel32/syscall.S                              |
|   src/arch/mipsbe32/syscall.S                              |
|                                                            |
|   One file per architecture. Each contains exactly one     |
|   exported function. This is the ONLY assembly in the      |
|   project (for Linux/FreeBSD targets).                     |
+============================================================+
                          |
                          | executes
                          v
+============================================================+
| Hardware: CPU syscall instruction                          |
|                                                            |
|   x86_64:  syscall                                         |
|   i686:    int 0x80 (Linux) / int 0x80 (FreeBSD)         |
|   aarch64: svc #0                                          |
|   armv5:   svc #0                                          |
|   mips*:   syscall                                         |
+============================================================+
```

## Header Include Strategy

When a blob source file needs to call `mmap`, it includes the appropriate wrapper header:

```
(conceptual, not actual code)
#include "sys/mman.h"   // provides mmap(), munmap(), mprotect()

// The preprocessor resolves:
// - The OS-specific wrapper (linux/ or freebsd/ prefix set via -I flags)
// - The arch-specific syscall number (via nested include of syscall_numbers.h)
// - The common assembly primitive declaration
```

The Bazel build system sets the include paths (`-I`) per target platform, so that:
- `#include "sys/mman.h"` resolves to `include/linux/sys/mman.h` for Linux targets.
- `#include "sys/mman.h"` resolves to `include/freebsd/sys/mman.h` for FreeBSD targets.
- The syscall number table for the target architecture is included transitively.

This means **blob source code is OS-agnostic**: it includes `"sys/mman.h"` and calls `mmap()` regardless of whether the target is Linux or FreeBSD. The build system wires in the correct implementation.

## Architecture-Specific Considerations

### i686 Linux vs FreeBSD

On i686, Linux passes syscall arguments in registers (`ebx`, `ecx`, `edx`, `esi`, `edi`, `ebp`), while FreeBSD passes them on the stack. The assembly stub MUST differ between Linux and FreeBSD on i686. This means:

- `src/arch/i686/syscall_linux.S` — uses register-based convention.
- `src/arch/i686/syscall_freebsd.S` — uses stack-based convention.

This is the one case where the assembly stub is per-OS as well as per-arch. All other architectures use the same instruction and register convention for both Linux and FreeBSD.

### MIPS Stack Arguments

On MIPS o32 ABI, only four arguments fit in registers (`$a0`-`$a3`). Arguments 5 and 6 must be placed on the stack at specific offsets. The assembly stub handles this, and the C calling convention naturally places the excess arguments on the stack when calling the stub as a 7-argument C function (syscall number + 6 args).

### armv5 ARM vs Thumb

Two separate assembly stubs exist for armv5:
- `src/arch/armv5/syscall.S` — ARM mode (`svc #0` in 32-bit ARM encoding).
- `src/arch/armv5/syscall_thumb.S` — Thumb mode (`svc #0` in 16-bit Thumb encoding).

The Thumb blob is compiled entirely in Thumb mode (`-mthumb`), and the syscall stub must also be Thumb.

## Dead Code Elimination Flow

```
Blob source includes sys/socket.h and sys/mman.h
  -> Compiler sees socket(), connect(), mmap(), mprotect(),
     plus 200+ other wrapper functions in the headers
  -> -ffunction-sections puts each in its own .text.* section
  -> Linker with --gc-sections traces from entry point
  -> Only socket(), connect(), mmap(), mprotect() are reachable
  -> All other wrapper sections are discarded
  -> Final ELF contains only the used syscall wrappers
```

## Derives From
- REQ-001
- REQ-002
- REQ-003
- REQ-004
