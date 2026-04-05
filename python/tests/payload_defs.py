"""Payload test definitions shared across test_payload_*.py modules.

Centralizes expected behavior, platform mappings, and runner type lookups
so that payload tests stay DRY.  Imported by both conftest.py (for fixtures)
and individual test modules (for assertions).

See: spec/verification/TEST-011-payload-pytest-suite.md
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path


# Import the registry (same technique as conftest.py).
def _project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / "MODULE.bazel").exists():
            return parent
    return Path.cwd()


_root = _project_root()
sys.path.insert(0, str(_root))
from tools.registry import OPERATING_SYSTEMS  # noqa: F401 — re-exported

sys.path.pop(0)


# ============================================================
# Payload expectation registry
# ============================================================


@dataclasses.dataclass(frozen=True)
class PayloadExpectation:
    """What a payload should produce when executed."""

    blob_type: str
    stdout: bytes | None = None  # exact match (None = don't check)
    stdout_contains: bytes | None = None  # substring match
    exit_code: int = 0
    needs_config: bool = False
    needs_infrastructure: bool = False
    timeout: float = 30.0


EXPECTATIONS: dict[str, PayloadExpectation] = {
    "hello": PayloadExpectation(
        blob_type="hello",
        stdout=b"Hello, world!\n",
        exit_code=0,
        timeout=10.0,
    ),
    "hello_windows": PayloadExpectation(
        blob_type="hello_windows",
        stdout=b"Hello, world!\n",
        exit_code=0,
        timeout=10.0,
    ),
    "alloc_jump": PayloadExpectation(
        blob_type="alloc_jump",
        stdout=b"PASS",
        exit_code=0,
        needs_config=True,
        timeout=15.0,
    ),
    "reflective_pe": PayloadExpectation(
        blob_type="reflective_pe",
        stdout_contains=b"LOADED",
        exit_code=0,
        needs_config=True,
        timeout=15.0,
    ),
    "stager_tcp": PayloadExpectation(
        blob_type="stager_tcp",
        stdout=b"TCP_OK",
        exit_code=0,
        needs_config=True,
        needs_infrastructure=True,
        timeout=30.0,
    ),
    "stager_fd": PayloadExpectation(
        blob_type="stager_fd",
        stdout=b"FD_OK",
        exit_code=0,
        needs_config=True,
        needs_infrastructure=True,
        timeout=15.0,
    ),
    "stager_pipe": PayloadExpectation(
        blob_type="stager_pipe",
        stdout_contains=b"PIPE_OK",
        exit_code=0,
        needs_config=True,
        needs_infrastructure=True,
        timeout=15.0,
    ),
    "stager_mmap": PayloadExpectation(
        blob_type="stager_mmap",
        stdout=b"MMAP_OK",
        exit_code=0,
        needs_config=True,
        timeout=15.0,
    ),
    "nacl_hello": PayloadExpectation(
        blob_type="nacl_hello",
        stdout=b"NaCl OK\n",
        exit_code=0,
        timeout=15.0,
    ),
}


# Which OSes each payload targets.
PAYLOAD_PLATFORMS: dict[str, list[str]] = {
    "hello": ["linux", "freebsd"],
    "hello_windows": ["windows"],
    "alloc_jump": ["linux", "freebsd", "windows"],
    "reflective_pe": ["windows"],
    "stager_tcp": ["linux", "freebsd", "windows"],
    "stager_fd": ["linux", "freebsd", "windows"],
    "stager_pipe": ["linux", "freebsd", "windows"],
    "stager_mmap": ["linux", "freebsd"],
    "nacl_hello": ["linux", "freebsd"],
}


# Runner type for each OS.
RUNNER_TYPE: dict[str, str] = {
    "linux": "linux",
    "freebsd": "freebsd",
    "windows": "windows",
}


def all_payload_combos() -> list[tuple[str, str, str]]:
    """Return all (blob_type, os, arch) combos from the payload/platform registry."""
    combos = []
    for blob_type, os_list in PAYLOAD_PLATFORMS.items():
        for os_name in os_list:
            os_entry = OPERATING_SYSTEMS.get(os_name)
            if os_entry is None:
                continue
            for arch in os_entry.architectures:
                combos.append((blob_type, os_name, arch))
    return sorted(combos)
