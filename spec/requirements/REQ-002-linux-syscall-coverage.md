# REQ-002: Complete Linux Syscall Header and Source Coverage

## Status
Accepted

## Statement

picblobs SHALL provide a C header and source system that exposes every Linux system call as a callable C function. Each wrapper function SHALL accept typed arguments matching the kernel's expected types and SHALL invoke the syscall assembly primitive (REQ-001) with the correct syscall number for the target architecture. The syscall number tables SHALL be derived from authoritative kernel sources and SHALL be organized per architecture.

## Rationale

Blob logic (memory allocation, file operations, socket operations, process control) must interact with the kernel exclusively through syscalls — there is no libc. Providing complete coverage means any blob type, present or future, can use any Linux syscall without requiring new assembly or ABI-level work. The header/source split allows blob authors to include only the headers they need, while the linker (with `-ffunction-sections -fdata-sections --gc-sections`) strips unused syscall wrappers from the final blob.

## Derives From
- VIS-001
- REQ-001

## Detailed Requirements

### Header Organization

The headers SHALL be organized by functional group, mirroring the logical groupings of Linux syscalls. The following groups are REQUIRED (non-exhaustive — the full set SHALL cover every syscall in the kernel's syscall table):

1. **Memory management**: mmap, munmap, mprotect, mremap, madvise, brk, msync, mlock, munlock, mlockall, munlockall, mincore, memfd_create, etc.
2. **File operations**: open, openat, close, read, write, pread64, pwrite64, lseek, readv, writev, sendfile, stat, fstat, lstat, fstatat, access, faccessat, truncate, ftruncate, rename, renameat, renameat2, unlink, unlinkat, mkdir, mkdirat, rmdir, link, linkat, symlink, symlinkat, readlink, readlinkat, chmod, fchmod, fchmodat, chown, fchown, fchownat, utimensat, etc.
3. **Process control**: fork, vfork, clone, clone3, execve, execveat, exit, exit_group, wait4, waitid, kill, tgkill, tkill, getpid, getppid, gettid, getuid, getgid, geteuid, getegid, setuid, setgid, setsid, getpgrp, setpgid, prctl, prlimit64, etc.
4. **Socket operations**: socket, bind, listen, accept, accept4, connect, sendto, recvfrom, sendmsg, recvmsg, shutdown, setsockopt, getsockopt, getpeername, getsockname, socketpair, etc.
5. **File descriptor operations**: dup, dup2, dup3, fcntl, ioctl, poll, ppoll, select, pselect6, epoll_create, epoll_create1, epoll_ctl, epoll_wait, epoll_pwait, eventfd, eventfd2, timerfd_create, timerfd_settime, timerfd_gettime, signalfd, signalfd4, inotify_init, inotify_init1, inotify_add_watch, inotify_rm_watch, pipe, pipe2, etc.
6. **Signal handling**: rt_sigaction, rt_sigprocmask, rt_sigreturn, rt_sigpending, rt_sigtimedwait, rt_sigqueueinfo, rt_sigsuspend, sigaltstack, etc.
7. **Time and clock**: clock_gettime, clock_settime, clock_getres, clock_nanosleep, nanosleep, gettimeofday, settimeofday, timer_create, timer_settime, timer_gettime, timer_getoverrun, timer_delete, etc.
8. **Filesystem and mount**: mount, umount2, pivot_root, chroot, statfs, fstatfs, sync, syncfs, fsync, fdatasync, fallocate, name_to_handle_at, open_by_handle_at, etc.
9. **Thread and futex**: futex, set_robust_list, get_robust_list, set_tid_address, etc.
10. **Miscellaneous**: getrandom, arch_prctl (x86_64), ptrace, personality, sysinfo, uname, getcwd, etc.

### Syscall Number Tables

For each supported architecture, picblobs SHALL maintain a table mapping each syscall name to its numeric value. These tables SHALL be:

1. Derived from the Linux kernel's `unistd.h` / syscall table for that architecture.
2. Stored as C header files with preprocessor defines (e.g., `#define __NR_mmap 9` on x86_64).
3. Organized per architecture (the syscall number for `mmap` differs between x86_64, i686, aarch64, armv5, mipsel, mipsbe).
4. Version-pinned to a specific kernel release, documented in the file header.

### Wrapper Function Conventions

Each syscall wrapper function SHALL:

1. Be declared in a header and defined in a corresponding source file (or as a static inline in the header).
2. Accept arguments with types matching the kernel ABI (e.g., `void *addr, size_t length, int prot` for mmap).
3. Pass the correct syscall number and arguments to the assembly primitive.
4. Return the raw kernel return value. Error handling conventions (negative return = error on Linux) SHALL be documented but not transformed — no errno emulation.
5. Be compiled with `-ffunction-sections` so that unused wrappers are eliminated by the linker's `--gc-sections` pass.

### Architecture-Specific Variations

Where Linux provides architecture-specific syscalls (e.g., `arch_prctl` on x86_64, `cacheflush` on MIPS/ARM), those SHALL be included in the architecture-specific header set.

Where an architecture lacks a syscall that exists on others (e.g., older architectures that use `mmap2` instead of `mmap`), the wrapper layer SHALL provide the correct variant for that architecture and MAY provide a compatibility wrapper that maps the common name to the architecture-appropriate syscall.

## Acceptance Criteria

1. For each supported Linux architecture, there exists a complete set of headers covering every syscall in the kernel's syscall table for that architecture.
2. Each wrapper function correctly invokes the syscall primitive with the right number and argument mapping.
3. Unused syscall wrappers do not appear in final blob binaries (verified by size inspection or symbol dump of pre-extraction ELF).
4. Syscall number tables cite their source kernel version.

## Related Decisions
- ADR-006

## Modeled By
- MOD-004

## Verified By
- TEST-002
