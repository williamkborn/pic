# Adding a New Architecture

1. Add an `Architecture` entry to `tools/registry.py`
2. Add the architecture to each supported `OperatingSystem.architectures` list
3. Add syscall numbers to the relevant `SYSCALL_NUMBERS` tables
4. Create `src/include/picblobs/syscall/{arch}.h` with the inline asm primitive
5. Create the matching runner `_start` stubs under `tests/runners/*/start/`
   for every runner type that will execute the architecture
6. Add a `bootlin.toolchain()` block to `MODULE.bazel`
7. Run `python tools/generate.py`
8. Run `python -m pytest python/tests/test_sync.py -v` (catches anything missed)
9. Build, stage, verify:
   ```bash
   python tools/stage_blobs.py --configs linux:{arch}
   picblobs-cli verify --os linux --arch {arch}
   ```
