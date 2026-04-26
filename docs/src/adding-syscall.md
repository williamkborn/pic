# Adding a New Syscall

1. Add the number to every architecture's table in `SYSCALL_NUMBERS` in `tools/registry.py`
2. Add a `SyscallDef` entry to `SYSCALL_DEFS` in `tools/registry.py`
3. Run `python tools/generate.py`
4. Run `python -m pytest python/tests/test_sync.py -v`

The generated `sys/{name}.h` will contain the numbers, OS guards, and wrapper.
