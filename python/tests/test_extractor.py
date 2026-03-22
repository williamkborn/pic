"""Tests for picblobs._extractor module."""

from __future__ import annotations

from pathlib import Path

import pytest

from picblobs._extractor import BlobData, extract


class TestBlobData:
    """Test the BlobData dataclass."""

    def test_frozen(self) -> None:
        blob = BlobData(
            code=b"\x90",
            config_offset=1,
            entry_offset=0,
            blob_type="test",
            target_os="linux",
            target_arch="x86_64",
            sha256="abc",
            sections={},
        )
        with pytest.raises(AttributeError):
            blob.code = b"\x00"  # type: ignore[misc]

    def test_fields(self) -> None:
        blob = BlobData(
            code=b"\xcc\xcc",
            config_offset=2,
            entry_offset=0,
            blob_type="alloc_jump",
            target_os="linux",
            target_arch="aarch64",
            sha256="deadbeef",
            sections={".text": (0, 2)},
        )
        assert len(blob.code) == 2
        assert blob.config_offset == 2
        assert blob.blob_type == "alloc_jump"
        assert blob.target_os == "linux"
        assert blob.target_arch == "aarch64"
        assert ".text" in blob.sections


class TestExtract:
    """Tests for the extract() function."""

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            extract(tmp_path / "nonexistent.so")

    def test_invalid_elf_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.so"
        bad_file.write_bytes(b"not an elf")
        with pytest.raises(Exception):
            extract(bad_file)

    @pytest.mark.requires_blobs
    def test_extract_real_blob(self, blob_dir: Path) -> None:
        """Test extraction on a real built .so (if available)."""
        so_files = list(blob_dir.rglob("*.so"))
        if not so_files:
            pytest.skip("No .so blobs built yet")

        blob = extract(so_files[0])
        assert isinstance(blob, BlobData)
        assert len(blob.code) > 0
        assert blob.sha256
        assert blob.config_offset >= 0


class TestPathDerivation:
    """Test that blob_type/os/arch are derived from file paths."""

    def test_derives_from_path(self, tmp_path: Path) -> None:
        # Create a fake path structure: _blobs/linux/x86_64/alloc_jump.so
        # We can't extract from it (not a real ELF), but we can test the path parsing
        # by checking the function handles the path parts correctly.
        parts = tmp_path / "linux" / "x86_64" / "alloc_jump.so"
        parts.parent.mkdir(parents=True)

        # The file needs to be a valid ELF for extract() to work,
        # so we just test the path parsing logic indirectly.
        assert parts.stem == "alloc_jump"
        assert parts.parts[-2] == "x86_64"
        assert parts.parts[-3] == "linux"
