# REQ-004: Per-Architecture Syscall Number Tables

## Status
Accepted

## Statement

picblobs SHALL maintain machine-readable syscall number tables for every supported OS and architecture combination. Each table SHALL map syscall names to their numeric identifiers. The tables SHALL be stored as C preprocessor defines in header files organized by OS and architecture. The tables SHALL be derived from authoritative sources and SHALL cite the specific OS kernel version from which they were extracted.

## Rationale

Syscall numbers are the fundamental interface between user-space PIC and the kernel. They vary across architectures on Linux (e.g., `mmap` is 9 on x86_64, 90 on i686, 222 on aarch64, 192 on armv5 as `mmap2`, 4090 on mipsel as `mmap2`). FreeBSD's numbers are architecture-independent but differ entirely from Linux's. Maintaining authoritative, versioned tables prevents silent bugs where a blob invokes the wrong syscall.

## Derives From
- REQ-002
- REQ-003

## Detailed Requirements

### Table Format

Each table SHALL be a C header file containing preprocessor defines of the form:

- One define per syscall, using the kernel's canonical naming convention (e.g., `__NR_` prefix for Linux, `SYS_` prefix for FreeBSD).
- A header comment documenting the source kernel version and extraction date.

### Table Organization

Tables SHALL be organized in the following directory structure within the C source tree:

- `include/{os}/{arch}/syscall_numbers.h` — e.g., `include/linux/x86_64/syscall_numbers.h`, `include/freebsd/aarch64/syscall_numbers.h`.

For FreeBSD, where syscall numbers are architecture-independent, a single shared table MAY be used with per-architecture includes that add any architecture-specific syscalls.

### Source Authority

- **Linux tables** SHALL be derived from the kernel's `arch/{arch}/include/generated/uapi/asm/unistd_64.h`, `unistd_32.h`, or equivalent generated headers for each architecture.
- **FreeBSD tables** SHALL be derived from `sys/kern/syscalls.master` or the generated `sys/sys/syscall.h`.

### Version Pinning

Each table file SHALL document:

1. The kernel/OS version it was extracted from (e.g., "Linux 6.8", "FreeBSD 14.0-RELEASE").
2. The date of extraction.
3. The method of extraction (manual, scripted, or tool reference).

### Completeness

The tables SHALL include every syscall defined in the source for that OS/architecture, including:

- Deprecated syscalls (marked with a comment indicating deprecation).
- Architecture-specific syscalls (e.g., `arch_prctl` on x86_64, `cacheflush` on MIPS/ARM).
- Multiplexed syscalls where applicable (e.g., `socketcall` on Linux i686 if the architecture uses it instead of individual socket syscalls).

## Acceptance Criteria

1. A table exists for every supported OS/architecture combination.
2. Every syscall number in each table matches the cited kernel version's authoritative source.
3. Each table file contains a version citation and extraction date.
4. No syscall is missing from the table relative to the cited source.

## Verified By
- TEST-002
