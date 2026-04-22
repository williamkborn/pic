"""picblobs — position-independent code blob library.

Provides pre-compiled PIC blobs for multiple OS/architecture targets.

In release mode, blobs are shipped as pre-extracted .bin files with
JSON sidecar metadata and a manifest.json catalog. In development mode,
falls back to extracting from .so files via pyelftools.

Usage:
    from picblobs import get_blob, list_blobs

    blob = get_blob("hello", "linux", "x86_64")
    print(len(blob.code), "bytes")
    print(blob.sections)
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from picblobs._builder import (
    AllocJumpBuilder,
    Blob,
    HelloBuilder,
    HelloWindowsBuilder,
    ReflectivePeBuilder,
    StagerFdBuilder,
    StagerMmapBuilder,
    StagerPipeBuilder,
    StagerTcpBuilder,
    UlExecBuilder,
)
from picblobs._enums import OS, Arch, BlobType, ValidationError
from picblobs._extractor import BlobData, extract, load_from_sidecar
from picblobs._introspect import (
    ConfigField,
    ConfigLayout,
    Target,
    blob_size,
    blob_types,
    build_hash,
    config_layout,
    djb2,
    djb2_dll,
    is_supported,
    raw_blob,
    targets,
)

__version__ = "0.1.0"
__all__ = [
    # Core extraction
    "get_blob",
    "list_blobs",
    "BlobData",
    "extract",
    "clear_cache",
    # Enums
    "OS",
    "Arch",
    "BlobType",
    "ValidationError",
    # Builder API (REQ-015)
    "Blob",
    "AllocJumpBuilder",
    "HelloBuilder",
    "HelloWindowsBuilder",
    "ReflectivePeBuilder",
    "StagerFdBuilder",
    "StagerMmapBuilder",
    "StagerPipeBuilder",
    "StagerTcpBuilder",
    "UlExecBuilder",
    # Introspection (REQ-016)
    "Target",
    "ConfigField",
    "ConfigLayout",
    "targets",
    "blob_types",
    "is_supported",
    "raw_blob",
    "blob_size",
    "build_hash",
    "config_layout",
    "djb2",
    "djb2_dll",
]

_PKG_DIR = Path(__file__).parent
_MANIFEST_PATH = _PKG_DIR / "manifest.json"
_BLOBS_DIR = _PKG_DIR / "blobs"

# .so directory (primary in development, fallback in release).
_SO_BLOB_DIR = _PKG_DIR / "_blobs"

# In a git checkout, prefer .so files (always fresh after stage_blobs.py)
# over pre-extracted .bin files (which may be stale). In an installed
# package, _blobs/ may not exist so .bin files are the primary path.
_DEV_MODE = (_PKG_DIR.parent.parent / ".git").is_dir()


def _load_manifest() -> dict | None:
    """Load and cache the release manifest, or None if not present."""
    if not hasattr(_load_manifest, "_cache"):
        if _MANIFEST_PATH.exists():
            _load_manifest._cache = json.loads(_MANIFEST_PATH.read_text())
        else:
            _load_manifest._cache = None
    return _load_manifest._cache


@functools.lru_cache(maxsize=64)
def get_blob(blob_type: str, target_os: str, target_arch: str) -> BlobData:
    """Load and extract a blob by type, OS, and architecture.

    Results are cached — repeated calls return the same BlobData instance.

    In dev mode (git checkout): prefers _blobs/{os}/{arch}/{type}.so
    (always fresh after stage_blobs.py).
    In release (installed package): prefers blobs/{type}.{os}.{arch}.bin.

    Args:
        blob_type: Blob type (e.g., "hello", "ul_exec").
        target_os: Target OS (e.g., "linux", "freebsd", "windows").
        target_arch: Target architecture (e.g., "x86_64", "aarch64").

    Returns:
        BlobData with extracted code bytes and metadata.

    Raises:
        FileNotFoundError: If no blob exists for the given combination.
    """
    so_path = _SO_BLOB_DIR / target_os / target_arch / f"{blob_type}.so"
    basename = f"{blob_type}.{target_os}.{target_arch}"
    bin_path = _BLOBS_DIR / f"{basename}.bin"
    json_path = _BLOBS_DIR / f"{basename}.json"

    if _DEV_MODE:
        # Development: prefer .so files (always fresh after stage_blobs.py)
        # over pre-extracted .bin files which may be stale.
        if so_path.exists():
            return extract(so_path, blob_type, target_os, target_arch)
        if bin_path.exists() and json_path.exists():
            return load_from_sidecar(bin_path, json_path)
    else:
        # Installed package: prefer fast .bin + .json path.
        if bin_path.exists() and json_path.exists():
            return load_from_sidecar(bin_path, json_path)
        if so_path.exists():
            return extract(so_path, blob_type, target_os, target_arch)

    raise FileNotFoundError(
        f"No blob for {blob_type}/{target_os}/{target_arch}: "
        f"checked {so_path} and {bin_path}"
    )


def clear_cache() -> None:
    """Clear the blob loading cache. Call after rebuilding blobs."""
    get_blob.cache_clear()
    if hasattr(_load_manifest, "_cache"):
        del _load_manifest._cache


def list_blobs() -> list[tuple[str, str, str]]:
    """Return all available (blob_type, target_os, target_arch) tuples.

    Primary path: reads manifest.json catalog (authoritative — the manifest
    is the single source of truth for release packages and is not validated
    against the filesystem; get_blob() is the point of failure for missing
    files).

    Fallback: walks the legacy _blobs/ directory.
    """
    manifest = _load_manifest()
    if manifest is not None:
        # Manifest is authoritative: trust the catalog without checking
        # individual .bin/.json files on disk.
        results = []
        for blob_type, entry in manifest.get("catalog", {}).items():
            for os_name, arches in entry.get("platforms", {}).items():
                for arch in arches:
                    results.append((blob_type, os_name, arch))
        return sorted(results)

    # Fallback: discover from filesystem (both .bin and .so directories).
    seen: set[tuple[str, str, str]] = set()
    results: list[tuple[str, str, str]] = []

    def _scan_so_dir() -> None:
        if _SO_BLOB_DIR.exists():
            for os_dir in sorted(_SO_BLOB_DIR.iterdir()):
                if not os_dir.is_dir():
                    continue
                for arch_dir in sorted(os_dir.iterdir()):
                    if not arch_dir.is_dir():
                        continue
                    for so_file in sorted(arch_dir.glob("*.so")):
                        entry = (so_file.stem, os_dir.name, arch_dir.name)
                        if entry not in seen:
                            seen.add(entry)
                            results.append(entry)

    def _scan_bin_dir() -> None:
        if _BLOBS_DIR.exists():
            for bin_file in sorted(_BLOBS_DIR.glob("*.bin")):
                parts = bin_file.stem.rsplit(".", 2)
                if len(parts) == 3:
                    entry = (parts[0], parts[1], parts[2])
                    if entry not in seen:
                        seen.add(entry)
                        results.append(entry)

    # In dev mode, .so files are authoritative; in release, .bin files are.
    if _DEV_MODE:
        _scan_so_dir()
        _scan_bin_dir()
    else:
        _scan_bin_dir()
        _scan_so_dir()

    return sorted(results)
