# Testing

## Full test suite

```bash
./testall
```

Runs all unit tests, sync tests, and payload execution tests. Unimplemented payload types skip gracefully.

## Filtered runs

```bash
./testall -v                           # verbose output
./testall --payload-only               # only payload execution tests
./testall --unit-only                  # only unit/sync tests
./testall --os linux --arch x86_64     # filter by platform
./testall --type hello                 # filter by blob type
./testall -k test_payload_hello        # pytest -k expression
```

## Via picblobs-cli

```bash
picblobs-cli test                          # run pytest
picblobs-cli test -v -k test_sync         # specific tests
picblobs-cli test --os linux --arch x86_64 # filtered
```

## Test architecture

Tests are organized by category:

| File | What it tests |
|---|---|
| `test_payload_hello.py` | hello + hello_windows execution on all platforms, structural checks |
| `test_payload_nacl.py` | nacl_hello self-test on all platforms, nacl_client + nacl_server e2e encrypted handshake |
| `test_payload_alloc_jump.py` | alloc_jump execution + edge cases (skips until implemented) |
| `test_payload_reflective.py` | reflective_pe loader (skips until implemented) |
| `test_payload_stager.py` | TCP, FD, pipe, mmap stagers with infrastructure fixtures (skips until implemented) |
| `test_payload_ul_exec.py` | Userland exec: load and run ELF binaries without execve() |
| `test_extractor.py` | Sidecar loading helpers |
| `test_release_loading.py` | Runtime loading path (.bin + .json sidecar, manifest) |
| `test_runner.py` | QEMU runner orchestration, blob preparation |
| `test_picblobs_cli.py` | CLI argument parsing and commands |
| `test_sync.py` | Registry sync: generated files, platform configs, syscall tables |

Payload tests are **registry-driven**: the test matrix is `blob_type x os x arch`, generated from `tools/registry.py`. Tests auto-skip when a blob or runner isn't staged. Adding a new payload and building it is sufficient to activate its tests.

See `spec/verification/TEST-011-payload-pytest-suite.md` for the full test specification.
