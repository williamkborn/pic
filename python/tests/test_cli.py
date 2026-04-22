"""Tests for picblobs.cli module."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from picblobs.cli import main, _parse_target


class TestParseTarget:
    """Test the os:arch target parser."""

    def test_valid_target(self) -> None:
        assert _parse_target("linux:x86_64") == ("linux", "x86_64")

    def test_valid_freebsd(self) -> None:
        assert _parse_target("freebsd:aarch64") == ("freebsd", "aarch64")

    def test_invalid_no_colon(self) -> None:
        with pytest.raises(Exception):
            _parse_target("linux_x86_64")


class TestListCommand:
    """Test the 'list' subcommand."""

    def test_list_runs(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="picblobs"):
            rc = main(["list"])
        assert rc == 0
        assert "BLOB TYPE" in caplog.text or "No blobs found" in caplog.text


class TestInfoCommand:
    """Test the 'info' subcommand."""

    def test_missing_blob_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["info", "nonexistent", "linux:x86_64"])
        assert rc == 1

    def test_needs_type_or_so(self) -> None:
        with pytest.raises(SystemExit):
            main(["info"])

    def test_so_import_error_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import picblobs.cli as cli

        monkeypatch.setattr(cli, "_setup_logging", lambda verbose=False: None)

        def _boom(path: str):
            raise ImportError("pyelftools missing")

        monkeypatch.setattr("picblobs._extractor.extract", _boom)
        rc = main(["info", "--so", "blob.so"])
        assert rc == 1


class TestExtractCommand:
    """Test the 'extract' subcommand."""

    def test_missing_blob_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["extract", "nonexistent", "linux:x86_64", "-o", "/dev/null"])
        assert rc == 1

    def test_so_import_error_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import picblobs.cli as cli

        monkeypatch.setattr(cli, "_setup_logging", lambda verbose=False: None)

        def _boom(path: str):
            raise ImportError("pyelftools missing")

        monkeypatch.setattr("picblobs._extractor.extract", _boom)
        rc = main(["extract", "--so", "blob.so", "-o", "/tmp/out.bin"])
        assert rc == 1


class TestRunCommand:
    """Test the 'run' subcommand."""

    def test_missing_blob_returns_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["run", "nonexistent", "linux:x86_64"])
        assert rc == 1

    def test_default_target(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Should fail (blob doesn't exist) but parse correctly
        rc = main(["run", "nonexistent"])
        assert rc == 1

    def test_needs_type_or_so(self) -> None:
        with pytest.raises(SystemExit):
            main(["run"])

    def test_dry_run_with_missing_blob(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["run", "nonexistent", "linux:x86_64", "--dry-run"])
        assert rc == 1  # blob not found, never reaches dry-run

    def test_so_import_error_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import picblobs.cli as cli

        monkeypatch.setattr(cli, "_setup_logging", lambda verbose=False: None)

        def _boom(path: str):
            raise ImportError("pyelftools missing")

        monkeypatch.setattr("picblobs._extractor.extract", _boom)
        rc = main(["run", "--so", "blob.so", "--dry-run"])
        assert rc == 1

    def test_so_uses_path_target_instead_of_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import picblobs.cli as cli
        from picblobs._extractor import BlobData
        from picblobs.runner import RunResult

        monkeypatch.setattr(cli, "_setup_logging", lambda verbose=False: None)

        blob = BlobData(
            code=b"\x90",
            config_offset=1,
            entry_offset=0,
            blob_type="alloc_jump",
            target_os="windows",
            target_arch="x86_64",
            sha256="abc",
            sections={},
        )
        calls: dict[str, object] = {}

        def _extract(path: str) -> BlobData:
            calls["path"] = path
            return blob

        def _run_blob(blob_data: BlobData, **kwargs) -> RunResult:
            calls["blob"] = blob_data
            calls["kwargs"] = kwargs
            return RunResult(
                stdout=b"",
                stderr=b"",
                exit_code=0,
                duration_s=0.0,
                command=["runner"],
            )

        monkeypatch.setattr("picblobs._extractor.extract", _extract)
        monkeypatch.setattr("picblobs.runner.run_blob", _run_blob)

        rc = main(["run", "--so", str(Path("blob.so")), "--dry-run"])
        assert rc == 0
        assert calls["blob"] is blob


class TestArgParsing:
    """Test argument parsing edge cases."""

    def test_no_args_exits(self) -> None:
        with pytest.raises(SystemExit):
            main([])

    def test_help_exits(self) -> None:
        with pytest.raises(SystemExit):
            main(["--help"])

    def test_run_help_exits(self) -> None:
        with pytest.raises(SystemExit):
            main(["run", "--help"])
