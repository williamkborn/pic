# REQ-017: Python Wheel Packaging with uv

## Status
Accepted

## Statement

picblobs SHALL be packaged as a Python wheel using uv as the project management and build tool. The wheel SHALL contain all pre-compiled blob binaries, their metadata files, the auto-generated ctypes config struct bindings, and the Python API source. The wheel SHALL be a platform-independent pure-Python wheel (since the blobs are data assets, not native extensions for the host platform). No compilation or toolchain installation SHALL be required by consumers at install time.

## Rationale

Packaging blobs as data assets in a pure-Python wheel means a single wheel works on any Python platform (Linux, macOS, Windows). The blobs are cross-compiled for their target platforms at build time; the host platform running Python is irrelevant. Using uv provides fast, modern Python project management with lockfile support and reproducible installs.

## Derives From
- VIS-001

## Detailed Requirements

### Project Structure

The Python project SHALL be structured as:

```
picblobs/
  __init__.py              # Public API (get_blob, list_blobs, clear_cache)
  __main__.py              # CLI entry point
  cli.py                   # CLI commands (list, info, extract, run, verify, test, build)
  _extractor.py            # Runtime ELF extraction via pyelftools
  runner.py                # QEMU test runner orchestration
  _qemu.py                 # QEMU binary mappings
  _generated/
    configs.py             # Auto-generated ctypes config structs (future)
  _blobs/
    linux/
      x86_64/hello.so      # Pre-compiled blob as .so (ELF with symtab)
      i686/hello.so
      ...
    freebsd/
      ...
    windows/
      ...
  _runners/                # Cross-compiled test runners (see ADR-021)
    linux/
      x86_64/runner
      i686/runner
      ...
```

### pyproject.toml

The `pyproject.toml` SHALL:

1. Use uv-compatible build system configuration.
2. Declare the package as `picblobs`.
3. Specify Python version requirement (>= 3.10).
4. Include `pyelftools` as a runtime dependency (required for .so extraction per ADR-018).
5. Include `pycparser` as a development-only dependency.
6. Include the `_blobs/` directory as package data.
7. Include the `_generated/` directory as package data.

### Wheel Type

The wheel SHALL be tagged as a pure-Python wheel (`py3-none-any`) since it contains no compiled extensions for the host platform. The blob binaries are data files, not shared libraries loaded by Python.

### Version

The package version SHALL follow semantic versioning. The version SHALL be incremented when:
- **Major**: Breaking changes to the Python API or config struct layouts.
- **Minor**: New blob types, new OS/architecture support, or new API features.
- **Patch**: Bug fixes to blob code, toolchain updates, or metadata corrections.

### Build Pipeline Integration

The wheel build process SHALL:

1. Run `picblobs build` (backed by `tools/stage_blobs.py`) which iterates over platform configs, runs `bazel build --config={config}` for each, and stages `.so` files and runner binaries into the package tree.
2. Run the config codegen tool to produce the Python ctypes bindings (future).
3. Build the wheel using `uv build` (hatchling backend).

This pipeline MAY be orchestrated by a top-level Makefile, a shell script, or a Bazel-to-Python integration rule.

### Testing

The wheel build SHALL be tested by:
1. Building the wheel.
2. Installing it in a clean virtual environment.
3. Running the Python test suite (which exercises the API, metadata, and config struct serialization — blob execution testing is separate, see TEST-008).

## Acceptance Criteria

1. `pip install picblobs` (or `uv pip install picblobs`) installs the package with no compilation step.
2. The installed package contains all blob binaries and metadata for every supported target.
3. `import picblobs` works on any Python 3.10+ platform.
4. The wheel is tagged `py3-none-any`.
5. The only runtime dependency beyond stdlib is `pyelftools` (for .so extraction per ADR-018).

## Related Decisions
- ADR-008

## Verified By
- TEST-008
