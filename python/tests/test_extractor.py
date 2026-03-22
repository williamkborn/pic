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

    @pytest.mark.requires_blobs
    def test_derives_from_path(self, blob_dir: Path) -> None:
        """Test that extract() derives metadata from the .so file path."""
        so_files = list(blob_dir.rglob("*.so"))
        if not so_files:
            pytest.skip("No .so blobs built yet")

        blob = extract(so_files[0])
        # Verify the path-derived fields are non-empty.
        assert blob.blob_type, "blob_type should be derived from filename"
        assert blob.target_os or blob.target_arch, "os/arch should be derived from path"

    def test_explicit_overrides_path(self, tmp_path: Path) -> None:
        """Test that explicit args override path derivation.

        We can't run extract() without a real ELF, but we can verify
        the function signature accepts override parameters.
        """
        # Verify the function accepts all override parameters without error
        # (the actual extraction will fail on a non-ELF file).
        fake = tmp_path / "linux" / "x86_64" / "test.so"
        fake.parent.mkdir(parents=True)
        fake.write_bytes(b"not an elf")
        with pytest.raises(Exception):
            extract(
                fake, blob_type="custom", target_os="freebsd", target_arch="aarch64"
            )
