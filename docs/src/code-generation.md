# Code Generation

Most boilerplate is generated from `tools/registry.py`:

```bash
python tools/generate.py           # regenerate all
python tools/generate.py --check   # verify freshness (CI)
```

## Generated files

- `src/include/picblobs/arch.h` -- architecture trait macros
- `src/include/picblobs/syscall.h` -- dispatcher to per-arch asm primitives
- `src/include/picblobs/picblobs.h` -- convenience header
- `src/include/picblobs/sys/*.h` -- per-syscall modules (numbers + wrappers)
- `platforms/BUILD.bazel`, `bazel/platforms.bzl`, `.bazelrc` -- Bazel platform configs
- `src/payload/BUILD.bazel` -- auto-discovered blob targets
- `tests/runners/linux/runner.c`, `tests/runners/freebsd/runner.c` -- test runner dispatchers

> **Note:** `tests/runners/windows/runner.c` is **not** generated. It is hand-written because the mock TEB/PEB environment requires specialized logic per architecture.

## The registry

`tools/registry.py` is the **single source of truth** for all platforms, architectures, syscall numbers, and build configurations. All generated files derive from it.
