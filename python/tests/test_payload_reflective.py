"""Payload tests for reflective_elf and reflective_pe blobs.

reflective_elf loads an ELF from memory and executes it (Linux/FreeBSD).
reflective_pe loads a PE from memory and executes it (Windows).

See: spec/verification/TEST-011-payload-pytest-suite.md
     spec/verification/TEST-005-reflective-loader-verification.md
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

# Inner test payload for reflective_elf (writes "LOADED" to stdout).
TEST_PAYLOAD_TYPE = "test_loaded"


def _reflective_elf_combos() -> list[tuple[str, str]]:
    combos = []
    for os_name in PAYLOAD_PLATFORMS.get("reflective_elf", []):
        os_entry = OPERATING_SYSTEMS.get(os_name)
        if os_entry is None:
            continue
        for arch in os_entry.architectures:
            combos.append((os_name, arch))
    return sorted(combos)


def _reflective_pe_combos() -> list[tuple[str, str]]:
    combos = []
    for os_name in PAYLOAD_PLATFORMS.get("reflective_pe", []):
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


def _build_reflective_elf_config(elf_data: bytes, target_arch: str) -> bytes:
    """Build config struct: elf_size (u32) + flags (u32) + elf_data."""
    flags = 0  # no special flags for basic test
    return struct.pack("<II", len(elf_data), flags) + elf_data


def _build_reflective_pe_config(pe_data: bytes, target_arch: str) -> bytes:
    """Build config struct: pe_size (u32) + flags (u32) + entry_type (u8) + pe_data."""
    flags = 0
    entry_type = 0  # DLL entry
    return struct.pack("<IIB", len(pe_data), flags, entry_type) + pe_data


# ---------------------------------------------------------------------------
# Reflective ELF loader tests
# ---------------------------------------------------------------------------


class TestReflectiveElfPayload:
    """Run reflective_elf on every supported platform."""

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize(
        "target_os,target_arch",
        _reflective_elf_combos(),
        ids=[f"{os}:{arch}" for os, arch in _reflective_elf_combos()],
    )
    def test_reflective_elf_loads_and_executes(
        self,
        target_os: str,
        target_arch: str,
    ) -> None:
        if not _blob_exists("reflective_elf", target_os, target_arch):
            pytest.skip(f"reflective_elf not staged: {target_os}/{target_arch}")

        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        if not _blob_exists(TEST_PAYLOAD_TYPE, "linux", target_arch):
            pytest.skip(
                f"Test payload not staged: {TEST_PAYLOAD_TYPE}/linux/{target_arch}"
            )

        runner_type = RUNNER_TYPE[target_os]
        try:
            from picblobs.runner import find_runner

            find_runner(runner_type, target_arch)
        except FileNotFoundError:
            pytest.skip(f"No {runner_type} runner for {target_arch}")

        exp = EXPECTATIONS["reflective_elf"]
        blob = get_blob("reflective_elf", target_os, target_arch)

        inner = get_blob(TEST_PAYLOAD_TYPE, "linux", target_arch)
        config = _build_reflective_elf_config(inner.code, target_arch)

        result = run_blob(blob, config=config, timeout=exp.timeout)

        assert result.exit_code == exp.exit_code, (
            f"reflective_elf {target_os}:{target_arch}: "
            f"exit_code={result.exit_code}, stderr={result.stderr!r}"
        )
        if exp.stdout is not None:
            assert result.stdout == exp.stdout


# ---------------------------------------------------------------------------
# Reflective PE loader tests
# ---------------------------------------------------------------------------


class TestReflectivePePayload:
    """Run reflective_pe on every supported platform."""

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize(
        "target_os,target_arch",
        _reflective_pe_combos(),
        ids=[f"{os}:{arch}" for os, arch in _reflective_pe_combos()],
    )
    def test_reflective_pe_loads_and_executes(
        self,
        target_os: str,
        target_arch: str,
    ) -> None:
        if not _blob_exists("reflective_pe", target_os, target_arch):
            pytest.skip(f"reflective_pe not staged: {target_os}/{target_arch}")

        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        runner_type = RUNNER_TYPE[target_os]
        try:
            from picblobs.runner import find_runner

            find_runner(runner_type, target_arch)
        except FileNotFoundError:
            pytest.skip(f"No {runner_type} runner for {target_arch}")

        exp = EXPECTATIONS["reflective_pe"]
        blob = get_blob("reflective_pe", target_os, target_arch)

        # For mock runner, use a dummy PE (the mock validates control flow).
        dummy_pe = b"MZ" + b"\x00" * 126
        config = _build_reflective_pe_config(dummy_pe, target_arch)

        result = run_blob(blob, config=config, timeout=exp.timeout)

        assert result.exit_code == exp.exit_code, (
            f"reflective_pe {target_os}:{target_arch}: "
            f"exit_code={result.exit_code}, stderr={result.stderr!r}"
        )
        if exp.stdout_contains is not None:
            assert exp.stdout_contains in result.stdout


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestReflectiveEdgeCases:
    """Invalid input handling for reflective loaders."""

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize(
        "target_arch",
        OPERATING_SYSTEMS["linux"].architectures,
        ids=OPERATING_SYSTEMS["linux"].architectures,
    )
    def test_corrupt_elf_exits_cleanly(self, target_arch: str) -> None:
        if not _blob_exists("reflective_elf", "linux", target_arch):
            pytest.skip(f"reflective_elf not staged: linux/{target_arch}")

        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        try:
            from picblobs.runner import find_runner

            find_runner("linux", target_arch)
        except FileNotFoundError:
            pytest.skip(f"No linux runner for {target_arch}")

        blob = get_blob("reflective_elf", "linux", target_arch)
        config = _build_reflective_elf_config(b"\x00" * 64, target_arch)
        result = run_blob(blob, config=config, timeout=10.0)
        assert result.exit_code != 0

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize(
        "target_arch",
        OPERATING_SYSTEMS["linux"].architectures,
        ids=OPERATING_SYSTEMS["linux"].architectures,
    )
    def test_pe_magic_rejected_by_elf_loader(self, target_arch: str) -> None:
        """Feed a PE file to the ELF loader."""
        if not _blob_exists("reflective_elf", "linux", target_arch):
            pytest.skip(f"reflective_elf not staged: linux/{target_arch}")

        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        try:
            from picblobs.runner import find_runner

            find_runner("linux", target_arch)
        except FileNotFoundError:
            pytest.skip(f"No linux runner for {target_arch}")

        blob = get_blob("reflective_elf", "linux", target_arch)
        config = _build_reflective_elf_config(b"MZ" + b"\x00" * 62, target_arch)
        result = run_blob(blob, config=config, timeout=10.0)
        assert result.exit_code != 0
