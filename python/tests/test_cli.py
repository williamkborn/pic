"""Tests for picblobs.cli module."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from picblobs.cli import _filter_verify_blobs, _parse_target, main


class TestParseTarget:
    """Test the os:arch target parser."""

    def test_valid_target(self) -> None:
        assert _parse_target("linux:x86_64") == ("linux", "x86_64")

    def test_valid_freebsd(self) -> None:
        assert _parse_target("freebsd:aarch64") == ("freebsd", "aarch64")

    def test_invalid_no_colon(self) -> None:
        with pytest.raises(ValueError):
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

    def test_so_import_error_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

    def test_so_import_error_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

    def test_so_import_error_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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


class TestVerifyCommand:
    """Test the 'verify' subcommand dispatch paths."""

    def test_verify_fallback_runner_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import picblobs.cli as cli

        monkeypatch.setattr(cli, "_setup_logging", lambda verbose=False: None)
        monkeypatch.setattr(
            "picblobs.list_blobs", lambda: [("hello", "linux", "x86_64")]
        )
        monkeypatch.setattr(
            "picblobs.get_blob",
            lambda blob_type, os_name, arch: SimpleNamespace(
                blob_type=blob_type, target_os=os_name, target_arch=arch
            ),
        )

        calls: list[tuple[str, str, str]] = []

        def _run_blob(blob, **kwargs):
            calls.append((blob.blob_type, blob.target_os, blob.target_arch))
            return SimpleNamespace(stdout=b"hello", stderr=b"", exit_code=0)

        monkeypatch.setattr("picblobs.runner.run_blob", _run_blob)

        rc = main(["verify", "--type", "hello", "--os", "linux", "--arch", "x86_64"])
        assert rc == 0
        assert calls == [("hello", "linux", "x86_64")]

    def test_verify_custom_runner_dispatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import picblobs.cli as cli

        monkeypatch.setattr(cli, "_setup_logging", lambda verbose=False: None)
        monkeypatch.setattr(
            "picblobs.list_blobs", lambda: [("alloc_jump", "linux", "x86_64")]
        )

        calls: list[tuple[str, str, float]] = []

        def _verify_alloc_jump(os_name: str, arch: str, timeout: float):
            calls.append((os_name, arch, timeout))
            return SimpleNamespace(stdout=b"ok", stderr=b"", exit_code=0)

        monkeypatch.setitem(cli._VERIFY_RUNNERS, "alloc_jump", _verify_alloc_jump)

        rc = main(
            ["verify", "--type", "alloc_jump", "--os", "linux", "--arch", "x86_64"]
        )
        assert rc == 0
        assert calls == [("linux", "x86_64", 30.0)]

    def test_verify_alloc_jump_uses_freebsd_inner_blob(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import picblobs.cli as cli

        monkeypatch.setattr(cli, "_setup_logging", lambda verbose=False: None)
        monkeypatch.setattr(
            "picblobs.list_blobs", lambda: [("alloc_jump", "freebsd", "x86_64")]
        )

        calls: list[tuple[str, str, str]] = []

        def _get_blob(blob_type: str, os_name: str, arch: str):
            calls.append((blob_type, os_name, arch))
            return SimpleNamespace(
                blob_type=blob_type,
                target_os=os_name,
                target_arch=arch,
                code=b"PASS",
            )

        monkeypatch.setattr("picblobs.get_blob", _get_blob)
        monkeypatch.setattr(
            "picblobs.runner.run_blob",
            lambda *args, **kwargs: SimpleNamespace(
                stdout=b"PASS", stderr=b"", exit_code=0
            ),
        )

        rc = main(
            ["verify", "--type", "alloc_jump", "--os", "freebsd", "--arch", "x86_64"]
        )
        assert rc == 0
        assert calls == [
            ("test_pass", "freebsd", "x86_64"),
            ("alloc_jump", "freebsd", "x86_64"),
        ]

    def test_verify_windows_stager_fd_uses_hello_windows_inner_blob(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import picblobs.cli as cli

        monkeypatch.setattr(cli, "_setup_logging", lambda verbose=False: None)
        monkeypatch.setattr(
            "picblobs.list_blobs", lambda: [("stager_fd", "windows", "x86_64")]
        )

        calls: list[tuple[str, str, str]] = []

        def _get_blob(blob_type: str, os_name: str, arch: str):
            calls.append((blob_type, os_name, arch))
            return SimpleNamespace(
                blob_type=blob_type,
                target_os=os_name,
                target_arch=arch,
                code=b"HELLO",
            )

        monkeypatch.setattr("picblobs.get_blob", _get_blob)
        monkeypatch.setattr(
            "picblobs.runner.run_blob",
            lambda *args, **kwargs: SimpleNamespace(
                stdout=b"Hello, world!", stderr=b"", exit_code=0
            ),
        )

        rc = main(
            ["verify", "--type", "stager_fd", "--os", "windows", "--arch", "x86_64"]
        )
        assert rc == 0
        assert calls == [
            ("hello_windows", "windows", "x86_64"),
            ("stager_fd", "windows", "x86_64"),
        ]

    def test_verify_filters_freebsd_to_x86_64(self) -> None:
        args = SimpleNamespace(os=None, arch=None, type=None)
        blobs = [
            ("hello", "freebsd", "aarch64"),
            ("hello", "freebsd", "x86_64"),
            ("ul_exec", "freebsd", "x86_64"),
            ("hello", "linux", "x86_64"),
        ]
        assert _filter_verify_blobs(blobs, args) == [
            ("hello", "freebsd", "x86_64"),
            ("hello", "linux", "x86_64"),
        ]
