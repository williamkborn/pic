# picblobs

Pre-compiled, position-independent code (PIC) blobs for loading and executing
arbitrary payloads on multiple operating systems and architectures. Eliminates
the need for hand-writing shellcode by providing tested, cross-platform PIC
stubs through a simple Python API.

## User Story

```text
As a developer who needs portable PIC payload stubs, I want a tested catalog
and builder API so I can assemble target-specific blobs without hand-writing
assembly for every OS and architecture.
```

## What's in the box

- **13 architectures**: x86_64, i686, aarch64, armv5 (ARM/Thumb), armv7, s390x, mipsel32, mipsbe32, sparcv8, powerpc, ppc64le, riscv64
- **3 operating systems**: Linux, FreeBSD, Windows
- **Freestanding C blobs** compiled with `-ffreestanding -nostdlib -fPIC -Os`
- **Python API** for loading, extracting, introspecting, and assembling blobs
- **CLI** (`picblobs-cli`) for inspecting, building, running, and verifying blobs
- **Cross-architecture testing** via QEMU user-static
- **Bazel 9 build system** with automatic Bootlin toolchain provisioning
- **Kernel toolkit** for red team lab exercises

## Verified status

The staged release catalog currently contains 368 blob/target entries across
24 OS/architecture targets. Use `picblobs-cli verify` for the full end-to-end
sweep, or filter it while iterating:

```text
$ picblobs-cli verify --os linux --arch x86_64 --type hello
[linux] hello
  linux:x86_64          OK   'Hello, world!'

1/1 passed
```
