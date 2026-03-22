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
  __init__.py          # Public API re-exports
  api.py               # Builder pattern implementation
  metadata.py          # Introspection API
  enums.py             # OS, Arch, BlobType enums
  djb2.py              # DJB2 hash utility
  _generated/
    configs.py         # Auto-generated ctypes config struct bindings
  _blobs/
    linux/
      x86_64/
        alloc_jump.bin       # Pre-compiled blob binary
        alloc_jump.meta.json # Metadata for this blob
        reflective_elf.bin
        reflective_elf.meta.json
        stager_tcp.bin
        stager_tcp.meta.json
        ...
      i686/
        ...
      aarch64/
        ...
      armv5_arm/
        ...
      armv5_thumb/
        ...
      mipsel32/
        ...
      mipsbe32/
        ...
    freebsd/
      ... (same arch structure)
    windows/
      x86_64/
        ...
      aarch64/
        ...
```

### pyproject.toml

The `pyproject.toml` SHALL:

1. Use uv-compatible build system configuration.
2. Declare the package as `picblobs`.
3. Specify Python version requirement (>= 3.10).
4. Include `pyelftools` and `pycparser` as build-time-only dependencies (not runtime).
5. Include `ctypes` as the only runtime dependency (part of the standard library — no external runtime dependencies).
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

1. Run `bazel build //blobs:all` to produce all blob binaries and metadata files.
2. Run the config codegen tool to produce the Python ctypes bindings.
3. Copy blob binaries and metadata into the `picblobs/_blobs/` directory.
4. Copy generated Python files into `picblobs/_generated/`.
5. Build the wheel using uv (or the uv-compatible build backend).

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
5. No runtime dependencies beyond the Python standard library are required.

## Related Decisions
- ADR-008

## Verified By
- TEST-008
