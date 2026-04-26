# Platform Support

## Architectures

| Architecture | Endianness | Bits | Traits |
|---|---|---|---|
| x86_64 | little | 64 | |
| i686 | little | 32 | uses_mmap2, is_32bit |
| aarch64 | little | 64 | openat_only |
| armv5_arm | little | 32 | uses_mmap2, is_32bit |
| armv5_thumb | little | 32 | uses_mmap2, is_32bit |
| armv7_thumb | little | 32 | uses_mmap2, is_32bit |
| s390x | big | 64 | uses_old_mmap |
| mipsel32 | little | 32 | uses_mmap2, needs_got_reloc, needs_trampoline, is_32bit |
| mipsbe32 | big | 32 | uses_mmap2, needs_got_reloc, needs_trampoline, is_32bit |
| sparcv8 | big | 32 | uses_mmap2, is_32bit |
| powerpc | big | 32 | uses_mmap2, needs_got_reloc, is_32bit |
| ppc64le | little | 64 | |
| riscv64 | little | 64 | openat_only |

### Architecture traits

Boolean flags controlling per-architecture decisions:

- **uses_mmap2**: Uses mmap2 syscall with page-unit offset
- **uses_old_mmap**: Uses old_mmap (args via struct pointer, not registers)
- **openat_only**: No legacy open syscall (use openat)
- **needs_got_reloc**: Needs GOT self-relocation (`PIC_SELF_RELOCATE`)
- **needs_trampoline**: Needs entry trampoline for PIC setup
- **is_32bit**: 32-bit architecture (affects lseek, etc.)

## Operating systems

| OS | Architectures | Blob types | Runner |
|---|---|---|---|
| Linux | x86_64, i686, aarch64, armv5_arm, armv5_thumb, armv7_thumb, s390x, mipsel32, mipsbe32, sparcv8, powerpc, ppc64le, riscv64 | hello, nacl, stagers, alloc_jump, ul_exec, verifier payloads | Native runner on host arch, QEMU user-static otherwise |
| FreeBSD | x86_64, i686, aarch64, armv5_arm, armv5_thumb, armv7_thumb, mipsel32, mipsbe32 | hello, nacl, stagers, alloc_jump, ul_exec on x86_64, verifier payloads | Linux-hosted syscall shim |
| Windows | x86_64, i686, aarch64 | hello_windows, stagers, alloc_jump, reflective_pe | Mock TEB/PEB on Linux |

## Current blob inventory

| Blob | OS | Description |
|---|---|---|
| `hello` | Linux, FreeBSD | Write "Hello, world!" via raw syscalls and exit |
| `hello_windows` | Windows | Write "Hello, world!" via PEB walk + DJB2 hash resolution of kernel32.dll exports (GetStdHandle, WriteFile, ExitProcess) |
| `nacl_hello` | Linux, FreeBSD | TweetNaCl self-test: encrypt/decrypt round-trip with crypto_secretbox (XSalsa20-Poly1305) and exit |
| `nacl_server` | Linux, FreeBSD | NaCl encrypted TCP server: bind, accept, decrypt message with crypto_secretbox, send encrypted ACK |
| `nacl_client` | Linux, FreeBSD | NaCl encrypted TCP client: connect, encrypt and send message, decrypt ACK from server |
| `nacl_server_hosted` | Linux, FreeBSD | Hosted-platform variant of `nacl_server` used by runner-backed tests |
| `nacl_client_hosted` | Linux, FreeBSD | Hosted-platform variant of `nacl_client` used by runner-backed tests |
| `alloc_jump` | Linux, FreeBSD, Windows | Allocate executable memory, copy an inner payload, and jump to it |
| `stager_tcp` | Linux, FreeBSD, Windows | Connect-back stager that reads a length-prefixed payload and jumps to it |
| `stager_fd` | Linux, FreeBSD, Windows | File-descriptor or stdin-handle stager |
| `stager_pipe` | Linux, FreeBSD, Windows | FIFO or named-pipe stager |
| `stager_mmap` | Linux, FreeBSD | File-backed mmap stager |
| `reflective_pe` | Windows | Reflective PE loader |
| `ul_exec` | Linux, FreeBSD x86_64 | Userland exec: load and execute ELF binaries without execve(), supporting static and dynamically linked PIE/non-PIE binaries |
| `test_pass`, `test_tcp_ok`, `test_fd_ok`, `test_pipe_ok`, `test_mmap_ok` | Linux, FreeBSD | Verifier-only inner payloads consumed by higher-level blob tests |
