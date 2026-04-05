# Adding a New Architecture

1. Add an `Architecture` entry to `tools/registry.py`
2. Add syscall numbers to `SYSCALL_NUMBERS["linux"]` in `registry.py`
3. Create `src/include/picblobs/syscall/{arch}.h` with the inline asm primitive
4. Create `tests/runners/linux/start/{arch}.h` with the `_start` stub
5. Add a `bootlin.toolchain()` block to `MODULE.bazel`
6. Run `python tools/generate.py`
7. Run `python -m pytest python/tests/test_sync.py -v` (catches anything missed)
8. Build, stage, verify:
   ```bash
   python tools/stage_blobs.py --configs linux:{arch}
   picblobs verify --arch {arch}
   ```
