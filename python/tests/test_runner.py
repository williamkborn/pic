"""Tests for picblobs.runner module."""

from __future__ import annotations

from pathlib import Path

import pytest

from picblobs._extractor import BlobData
from picblobs.runner import (
    QEMU_BINARIES,
    RunResult,
    _text_end,
    build_blob_command,
    find_qemu,
    find_runner,
    prepare_blob,
    run_blob,
)


class TestQemuBinaryMap:
    """Test QEMU binary name resolution."""

    def test_all_architectures_mapped(self) -> None:
        # Sync test (test_sync.py) verifies completeness against the registry.
        # Here we just check the map is non-empty and values look like QEMU binaries.
        assert len(QEMU_BINARIES) > 0
        for arch, binary in QEMU_BINARIES.items():
            assert binary.startswith("qemu-"), (
                f"{arch}: {binary} doesn't look like a QEMU binary"
            )
            assert binary.endswith("-static"), (
                f"{arch}: {binary} doesn't end with -static"
            )

    def test_unknown_arch_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown architecture"):
            find_qemu("not-a-real-arch")

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


class TestTextEnd:
    """_text_end bounds the FreeBSD syscall patcher to the code region."""

    def _blob_with_sections(self, sections: dict[str, tuple[int, int]]) -> BlobData:
        return BlobData(
            code=b"\x00" * 256,
            config_offset=256,
            entry_offset=0,
            blob_type="test",
            target_os="freebsd",
            target_arch="x86_64",
            sha256="",
            sections=sections,
        )

    def test_single_text_section(self) -> None:
        blob = self._blob_with_sections({".text": (0, 0x40), ".rodata": (0x40, 0x10)})
        assert _text_end(blob) == 0x40

    def test_multiple_text_sections_takes_max(self) -> None:
        blob = self._blob_with_sections(
            {".text.pic_entry": (0, 0x30), ".text.helper": (0x40, 0x20)}
        )
        assert _text_end(blob) == 0x60

    def test_no_text_section_returns_zero(self) -> None:
        blob = self._blob_with_sections({".rodata": (0, 0x10)})
        assert _text_end(blob) == 0


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


class TestRunBlobDryRun:
    def test_dry_run_does_not_prepare_temp_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        blob = BlobData(
            code=b"\x90",
            config_offset=1,
            entry_offset=0,
            blob_type="test",
            target_os="linux",
            target_arch="x86_64",
            sha256="",
            sections={},
        )

        monkeypatch.setattr("picblobs.runner.find_runner", lambda *_: Path("/runner"))
        monkeypatch.setattr(
            "picblobs.runner._build_command",
            lambda runner_path, blob_file, arch, extra=None: [
                str(runner_path),
                str(blob_file),
            ],
        )

        def _boom(*args, **kwargs):
            raise AssertionError("prepare_blob should not be called in dry_run")

        monkeypatch.setattr("picblobs.runner.prepare_blob", _boom)

        result = run_blob(blob, dry_run=True)
        assert result.exit_code == 0
        assert result.command == ["/runner", "test_linux_x86_64.bin"]
        assert result.blob_file == "test_linux_x86_64.bin"


class TestBuildBlobCommand:
    def test_freebsd_includes_text_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        blob = BlobData(
            code=b"\x00" * 64,
            config_offset=64,
            entry_offset=0,
            blob_type="test",
            target_os="freebsd",
            target_arch="x86_64",
            sha256="",
            sections={".text": (0, 0x20), ".rodata": (0x20, 0x10)},
        )

        monkeypatch.setattr(
            "picblobs.runner._build_command",
            lambda runner_path, blob_file, arch, extra=None: [
                str(runner_path),
                str(blob_file),
                *(extra or []),
            ],
        )

        cmd = build_blob_command(blob, Path("/runner"), Path("/blob.bin"))
        assert cmd == ["/runner", "/blob.bin", "0x20"]

    def test_linux_has_no_freebsd_extra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        blob = BlobData(
            code=b"\x00" * 64,
            config_offset=64,
            entry_offset=0,
            blob_type="test",
            target_os="linux",
            target_arch="x86_64",
            sha256="",
            sections={".text": (0, 0x20)},
        )

        monkeypatch.setattr(
            "picblobs.runner._build_command",
            lambda runner_path, blob_file, arch, extra=None: [
                str(runner_path),
                str(blob_file),
                *(extra or []),
            ],
        )

        cmd = build_blob_command(blob, Path("/runner"), Path("/blob.bin"))
        assert cmd == ["/runner", "/blob.bin"]
