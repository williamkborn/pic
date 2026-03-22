"""Tests for picblobs.cli module."""

from __future__ import annotations

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

    def test_list_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "BLOB TYPE" in out or "No blobs found" in out


class TestInfoCommand:
    """Test the 'info' subcommand."""

    def test_missing_blob_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["info", "nonexistent", "linux:x86_64"])
        assert rc == 1

    def test_needs_type_or_so(self) -> None:
        with pytest.raises(SystemExit):
            main(["info"])


class TestExtractCommand:
    """Test the 'extract' subcommand."""

    def test_missing_blob_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["extract", "nonexistent", "linux:x86_64", "-o", "/dev/null"])
        assert rc == 1


class TestRunCommand:
    """Test the 'run' subcommand."""

    def test_missing_blob_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["run", "nonexistent", "linux:x86_64"])
        assert rc == 1

    def test_default_target(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Should fail (blob doesn't exist) but parse correctly
        rc = main(["run", "nonexistent"])
        assert rc == 1

    def test_needs_type_or_so(self) -> None:
        with pytest.raises(SystemExit):
            main(["run"])

    def test_dry_run_with_missing_blob(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["run", "nonexistent", "linux:x86_64", "--dry-run"])
        assert rc == 1  # blob not found, never reaches dry-run


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
