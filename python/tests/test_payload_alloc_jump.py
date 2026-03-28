"""Payload tests for alloc_jump blob.

The alloc_jump blob allocates RWX memory, copies a payload into it, and
jumps to it.  Tests supply a small test payload (test_pass) that writes
"PASS" to stdout and exits 0.

See: spec/verification/TEST-011-payload-pytest-suite.md
     spec/verification/TEST-004-alloc-jump-verification.md
"""

from __future__ import annotations

import struct

import pytest

from picblobs import get_blob
from picblobs.runner import is_arch_skip_rosetta, run_blob

from payload_defs import EXPECTATIONS, OPERATING_SYSTEMS, PAYLOAD_PLATFORMS, RUNNER_TYPE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Map alloc_jump's inner test payload type (uses Linux syscalls).
TEST_PAYLOAD_TYPE = "test_pass"


def _alloc_jump_combos() -> list[tuple[str, str]]:
    """Return (os, arch) for alloc_jump."""
    combos = []
    for os_name in PAYLOAD_PLATFORMS.get("alloc_jump", []):
        os_entry = OPERATING_SYSTEMS.get(os_name)
        if os_entry is None:
            continue
        for arch in os_entry.architectures:
            combos.append((os_name, arch))
    return sorted(combos)


def _blob_exists(blob_type: str, target_os: str, target_arch: str) -> bool:
    try:
        get_blob(blob_type, target_os, target_arch)
        return True
    except FileNotFoundError:
        return False


def _build_alloc_jump_config(
    payload_bytes: bytes,
    target_arch: str,
) -> bytes:
    """Build config struct for alloc_jump: payload_size (u32) + payload_data."""
    return struct.pack("<I", len(payload_bytes)) + payload_bytes


# ---------------------------------------------------------------------------
# Core execution tests
# ---------------------------------------------------------------------------


class TestAllocJumpPayload:
    """Run alloc_jump on every supported platform."""

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize(
        "target_os,target_arch",
        _alloc_jump_combos(),
        ids=[f"{os}:{arch}" for os, arch in _alloc_jump_combos()],
    )
    def test_alloc_jump_executes_inner_payload(
        self,
        target_os: str,
        target_arch: str,
    ) -> None:
        if not _blob_exists("alloc_jump", target_os, target_arch):
            pytest.skip(f"alloc_jump not staged: {target_os}/{target_arch}")

        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        # The inner test payload uses Linux syscalls, so load from linux.
        if not _blob_exists(TEST_PAYLOAD_TYPE, "linux", target_arch):
            pytest.skip(f"Test payload not staged: {TEST_PAYLOAD_TYPE}/linux/{target_arch}")

        runner_type = RUNNER_TYPE[target_os]
        try:
            from picblobs.runner import find_runner

            find_runner(runner_type, target_arch)
        except FileNotFoundError:
            pytest.skip(f"No {runner_type} runner for {target_arch}")

        exp = EXPECTATIONS["alloc_jump"]
        blob = get_blob("alloc_jump", target_os, target_arch)

        # Load the inner test payload's raw code.
        inner = get_blob(TEST_PAYLOAD_TYPE, "linux", target_arch)
        config = _build_alloc_jump_config(inner.code, target_arch)

        result = run_blob(blob, config=config, timeout=exp.timeout)

        assert result.exit_code == exp.exit_code, (
            f"alloc_jump {target_os}:{target_arch}: "
            f"exit_code={result.exit_code}, stderr={result.stderr!r}"
        )
        if exp.stdout is not None:
            assert result.stdout == exp.stdout, (
                f"alloc_jump {target_os}:{target_arch}: "
                f"stdout={result.stdout!r}, expected={exp.stdout!r}"
            )


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestAllocJumpEdgeCases:
    """Error handling and size checks for alloc_jump."""

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize(
        "target_arch",
        OPERATING_SYSTEMS["linux"].architectures,
        ids=OPERATING_SYSTEMS["linux"].architectures,
    )
    def test_absurd_payload_size_exits_cleanly(
        self,
        target_arch: str,
    ) -> None:
        if not _blob_exists("alloc_jump", "linux", target_arch):
            pytest.skip(f"alloc_jump not staged: linux/{target_arch}")

        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        try:
            from picblobs.runner import find_runner

            find_runner("linux", target_arch)
        except FileNotFoundError:
            pytest.skip(f"No linux runner for {target_arch}")

        blob = get_blob("alloc_jump", "linux", target_arch)
        # Request an impossible allocation size.
        config = struct.pack("<I", 0xFFFFFFFF)
        result = run_blob(blob, config=config, timeout=10.0)
        assert result.exit_code != 0, (
            f"alloc_jump linux:{target_arch}: should fail with absurd size"
        )

    @pytest.mark.parametrize(
        "target_os,target_arch",
        _alloc_jump_combos(),
        ids=[f"{os}:{arch}" for os, arch in _alloc_jump_combos()],
    )
    def test_alloc_jump_under_512_bytes(
        self,
        target_os: str,
        target_arch: str,
    ) -> None:
        if not _blob_exists("alloc_jump", target_os, target_arch):
            pytest.skip(f"alloc_jump not staged: {target_os}/{target_arch}")

        blob = get_blob("alloc_jump", target_os, target_arch)
        assert len(blob.code) < 512, (
            f"alloc_jump {target_os}:{target_arch}: "
            f"code size {len(blob.code)} bytes exceeds 512 byte limit"
        )
