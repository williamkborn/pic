"""picblobs — position-independent code blob library.

Provides pre-compiled PIC blobs for multiple OS/architecture targets.
Blobs are shipped as .so files and extracted at runtime via pyelftools.

Usage:
    from picblobs import get_blob, list_blobs

    blob = get_blob("alloc_jump", "linux", "x86_64")
    print(len(blob.code), "bytes")
    print(blob.sections)
"""

from __future__ import annotations

import functools
from pathlib import Path

from picblobs._extractor import BlobData, extract

__version__ = "0.1.0"
__all__ = ["get_blob", "list_blobs", "BlobData", "extract"]

_BLOB_DIR = Path(__file__).parent / "_blobs"


@functools.lru_cache(maxsize=None)
def get_blob(blob_type: str, target_os: str, target_arch: str) -> BlobData:
    """Load and extract a blob by type, OS, and architecture.

    Results are cached — repeated calls return the same BlobData instance.

    Args:
        blob_type: Blob type (e.g., "alloc_jump", "stager_tcp").
        target_os: Target OS (e.g., "linux", "freebsd", "windows").
        target_arch: Target architecture (e.g., "x86_64", "aarch64").

    Returns:
        BlobData with extracted code bytes and metadata.

    Raises:
        FileNotFoundError: If no blob exists for the given combination.
    """
    so_path = _BLOB_DIR / target_os / target_arch / f"{blob_type}.so"
    if not so_path.exists():
        raise FileNotFoundError(
            f"No blob for {blob_type}/{target_os}/{target_arch}: {so_path}"
        )
    return extract(so_path, blob_type, target_os, target_arch)


def list_blobs() -> list[tuple[str, str, str]]:
    """Return all available (blob_type, target_os, target_arch) tuples."""
    results = []
    if not _BLOB_DIR.exists():
        return results

    for os_dir in sorted(_BLOB_DIR.iterdir()):
        if not os_dir.is_dir():
            continue
        for arch_dir in sorted(os_dir.iterdir()):
            if not arch_dir.is_dir():
                continue
            for so_file in sorted(arch_dir.glob("*.so")):
                results.append((so_file.stem, os_dir.name, arch_dir.name))

    return results
