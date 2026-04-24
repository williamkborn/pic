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

## What's in the box

- **9 architectures**: x86_64, i686, aarch64, armv5 (ARM/Thumb), armv7, s390x, mipsel32, mipsbe32
- **3 operating systems**: Linux, FreeBSD, Windows
- **Freestanding C blobs** compiled with `-ffreestanding -nostdlib -fPIC -Os`
- **Python API** for loading, extracting, and running blobs
- **CLI** (`picblobs-cli`) for inspecting, running, and verifying blobs
- **Cross-architecture testing** via QEMU user-static
- **Bazel 9 build system** with automatic Bootlin toolchain provisioning
- **Kernel toolkit** for red team lab exercises

## Verified status

```text
$ picblobs-cli verify
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
