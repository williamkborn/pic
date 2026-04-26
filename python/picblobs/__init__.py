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
import os
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
    "OS",
    "AllocJumpBuilder",
    "Arch",
    "Blob",
    "BlobData",
    "BlobType",
    "ConfigField",
    "ConfigLayout",
    "HelloBuilder",
    "HelloWindowsBuilder",
    "ReflectivePeBuilder",
    "StagerFdBuilder",
    "StagerMmapBuilder",
    "StagerPipeBuilder",
    "StagerTcpBuilder",
    "Target",
    "UlExecBuilder",
    "ValidationError",
    "blob_size",
    "blob_types",
    "build_hash",
    "clear_cache",
    "config_layout",
    "djb2",
    "djb2_dll",
    "extract",
    "get_blob",
    "is_supported",
    "list_blobs",
    "raw_blob",
    "targets",
]

_PKG_DIR = Path(__file__).parent
_MANIFEST_PATH = _PKG_DIR / "manifest.json"
_BLOBS_DIR = _PKG_DIR / "blobs"

# .so directory (primary in development, fallback in release).
_SO_BLOB_DIR = _PKG_DIR / "_blobs"


def _detect_dev_mode() -> bool:
    """Return whether blob loading should prefer development .so artifacts."""
    mode = os.environ.get("PICBLOBS_LOAD_MODE", "").strip().lower()
    if mode in {"release", "sidecar", "bin"}:
        return False
    if mode in {"dev", "development", "so"}:
        return True
    return (_PKG_DIR.parent.parent / ".git").is_dir()


# In a git checkout, prefer .so files (always fresh after stage_blobs.py)
# over pre-extracted .bin files (which may be stale). CI and other callers
# can force release-mode loading with PICBLOBS_LOAD_MODE=release.
_DEV_MODE = _detect_dev_mode()


def _load_manifest() -> dict | None:
    """Load and cache the release manifest, or None if not present."""
    if not hasattr(_load_manifest, "_cache"):
        if _MANIFEST_PATH.exists():
            _load_manifest._cache = json.loads(_MANIFEST_PATH.read_text())
        else:
            _load_manifest._cache = None
    return _load_manifest._cache


def _registry_list_blobs() -> list[tuple[str, str, str]]:
    """Return registry-declared blobs for source-tree introspection.

    This is only used as a last-resort development fallback when neither
    a manifest nor any staged blob files are present. It keeps the support
    matrix and config-layout APIs usable in a clean checkout without
    pretending that raw blob bytes are available.
    """
    from picblobs._introspect import _registry_blob_types

    registry = _registry_blob_types()
    if registry is None:
        return []

    results = {
        ((bt.staged_name or bt.name), os_name, arch_name)
        for bt in registry.values()
        for os_name, arches in bt.platforms.items()
        for arch_name in arches
    }
    return sorted(results)


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

    Development fallback: walks staged .so/.bin directories. If those are
    also absent in a source checkout, fall back to the canonical registry so
    introspection APIs still expose the declared support matrix.
    """
    manifest = _load_manifest()
    if manifest is not None:
        # Manifest is authoritative: trust the catalog without checking
        # individual .bin/.json files on disk.
        results = []
        for blob_type, entry in manifest.get("catalog", {}).items():
            for os_name, arches in entry.get("platforms", {}).items():
                results.extend((blob_type, os_name, arch) for arch in arches)
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

    if not results:
        return _registry_list_blobs()

    return sorted(results)
