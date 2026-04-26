# Test Runners

Testing runs from a Linux host. The runner executes natively when the runner
architecture matches the host (`x86_64` on the usual dev/CI path), and uses
QEMU user-static for cross-architecture execution. Three runner types handle
the three target OSes:

| Runner | How it works | Binary type |
|---|---|---|
| **Linux** | Loads blob into RWX memory, jumps to it. Blob executes real Linux syscalls, emulated by QEMU. End-to-end integration test. | Freestanding Linux binary, per-arch |
| **Windows** | Constructs mock TEB/PEB/LDR structures with fake kernel32.dll export table. Blob resolves APIs via DJB2 hash, calls mock implementations (GetStdHandle -> fd, WriteFile -> Linux write, ExitProcess -> exit_group). | Freestanding Linux binary, per-arch |
| **FreeBSD** | Linux-hosted syscall shim validates FreeBSD syscall numbers and arguments. | Freestanding Linux binary, per-arch |

## Windows runner

The Windows runner is **hand-written** (not generated) because it has complex mock logic. It supports x86_64 (gs-based TEB), i686 (fs-based TEB via set_thread_area), and aarch64 (tpidr_el0-based TEB). Build it with a Linux config since it's a Linux binary:

```bash
bazel build --config=linux_x86_64 //tests/runners/windows:runner
bazel build --config=linux_i686 //tests/runners/windows:runner
bazel build --config=linux_aarch64 //tests/runners/windows:runner
```
