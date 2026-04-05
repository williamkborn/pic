# Platform Support

## Architectures

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
| Linux | x86_64, i686, aarch64, armv5_arm, armv5_thumb, armv7_thumb, s390x, mipsel32, mipsbe32 | hello, nacl_hello, nacl_client, nacl_server (+ future: alloc_jump, stagers, reflective_elf) | Direct execution via QEMU user-static |
| FreeBSD | x86_64, i686, aarch64, armv5_arm, armv5_thumb, armv7_thumb, mipsel32, mipsbe32 | hello (+ future: alloc_jump, stagers, reflective_elf) | Syscall shim (WIP) |
| Windows | x86_64, i686, aarch64 | hello_windows (+ future: alloc_jump, stagers, reflective_pe) | Mock TEB/PEB on Linux |

## Current blob inventory

| Blob | OS | Description |
|---|---|---|
| `hello` | Linux, FreeBSD | Write "Hello, world!" via raw syscalls and exit |
| `hello_windows` | Windows | Write "Hello, world!" via PEB walk + DJB2 hash resolution of kernel32.dll exports (GetStdHandle, WriteFile, ExitProcess) |
| `nacl_hello` | Linux, FreeBSD | TweetNaCl self-test: encrypt/decrypt round-trip with crypto_secretbox (XSalsa20-Poly1305) and exit |
| `nacl_server` | Linux, FreeBSD | NaCl encrypted TCP server: bind, accept, decrypt message with crypto_secretbox, send encrypted ACK |
| `nacl_client` | Linux, FreeBSD | NaCl encrypted TCP client: connect, encrypt and send message, decrypt ACK from server |
| `ul_exec` | Linux | Userland exec: load and execute ELF binaries without execve(), supporting static and dynamically linked PIE/non-PIE binaries |
