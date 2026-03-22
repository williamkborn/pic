"""Tests for picblobs.runner module."""

from __future__ import annotations

from pathlib import Path

import pytest

from picblobs._extractor import BlobData
from picblobs.runner import (
    QEMU_BINARIES,
    RunResult,
    find_qemu,
    find_runner,
    prepare_blob,
)


class TestQemuBinaryMap:
    """Test QEMU binary name resolution."""

    def test_all_architectures_mapped(self) -> None:
        expected = {"x86_64", "i686", "aarch64", "armv5_arm", "armv5_thumb",
                    "mipsel32", "mipsbe32"}
        assert set(QEMU_BINARIES.keys()) == expected

    def test_unknown_arch_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown architecture"):
            find_qemu("riscv64")

    @pytest.mark.requires_qemu
    def test_find_qemu_x86_64(self) -> None:
        path = find_qemu("x86_64")
        assert path.exists()


class TestFindRunner:
    """Test runner binary discovery."""

    def test_missing_runner_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            find_runner("linux", search_paths=[Path("/nonexistent")])

    @pytest.mark.requires_runners
    def test_find_linux_runner(self) -> None:
        runner = find_runner("linux")
        assert runner.exists()
        assert runner.is_file()


class TestPrepareBlob:
    """Test blob preparation (writing code + config to temp file)."""

    def _make_blob(self, code: bytes = b"\xcc") -> BlobData:
        return BlobData(
            code=code,
            config_offset=len(code),
            entry_offset=0,
            blob_type="test",
            target_os="linux",
            target_arch="x86_64",
            sha256="",
            sections={},
        )

    def test_writes_code(self, tmp_path: Path) -> None:
        blob = self._make_blob(b"\x90\x90\x90")
        path = prepare_blob(blob, output_dir=tmp_path)
        assert path.exists()
        assert path.read_bytes() == b"\x90\x90\x90"

    def test_writes_code_with_config(self, tmp_path: Path) -> None:
        blob = self._make_blob(b"\x90\x90")
        config = b"\xde\xad"
        path = prepare_blob(blob, config=config, output_dir=tmp_path)
        data = path.read_bytes()
        assert data[:2] == b"\x90\x90"
        assert data[2:4] == b"\xde\xad"

    def test_pads_to_config_offset(self, tmp_path: Path) -> None:
        blob = BlobData(
            code=b"\x90",
            config_offset=8,
            entry_offset=0,
            blob_type="test",
            target_os="linux",
            target_arch="x86_64",
            sha256="",
            sections={},
        )
        config = b"\xff\xff"
        path = prepare_blob(blob, config=config, output_dir=tmp_path)
        data = path.read_bytes()
        assert len(data) >= 10
        assert data[8:10] == b"\xff\xff"


class TestRunResult:
    """Test RunResult dataclass."""

    def test_fields(self) -> None:
        r = RunResult(
            stdout=b"PASS",
            stderr=b"",
            exit_code=0,
            duration_s=0.1,
            command=["./runner", "blob.bin"],
        )
        assert r.stdout == b"PASS"
        assert r.exit_code == 0
        assert r.duration_s == pytest.approx(0.1)
