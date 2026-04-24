"""TEST-012: picblobs-cli verification.

Exercises every sub-command in ``picblobs_cli.cli`` plus the
``find_runner`` discovery contract (picblobs-cli bundle preferred over
the Bazel build tree).
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import picblobs
import picblobs_cli
import pytest
from click.testing import CliRunner
from picblobs_cli.cli import main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def qemu_available() -> bool:
    return shutil.which("qemu-x86_64-static") is not None


def _require_qemu(flag: bool) -> None:
    if not flag:
        pytest.skip("qemu-user-static not installed")


# ---------------------------------------------------------------------------
# 12.1 Package imports
# ---------------------------------------------------------------------------


class TestPackageImports:
    def test_picblobs_cli_importable(self) -> None:
        assert picblobs_cli.__version__

    def test_version_matches_picblobs(self) -> None:
        assert picblobs_cli.__version__ == picblobs.__version__

    def test_main_is_click_command(self) -> None:
        import click

        assert isinstance(main, click.Command)

    def test_runners_dir_resolves(self) -> None:
        p = picblobs_cli.runners_dir()
        assert p.exists(), p
        assert (p / "linux" / "x86_64" / "runner").exists()


# ---------------------------------------------------------------------------
# 12.2 Console script entry point
# ---------------------------------------------------------------------------


class TestConsoleScript:
    def test_help_exits_zero(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["--help"])
        assert r.exit_code == 0

    def test_help_lists_commands(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["--help"])
        for cmd in ("run", "verify", "build", "list-runners", "info"):
            assert cmd in r.output, cmd

    def test_version_flag(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["--version"])
        assert r.exit_code == 0
        assert picblobs_cli.__version__ in r.output

    def test_python_dash_m_entry(self) -> None:
        """``python -m picblobs_cli --help`` works as a console entry."""
        r = subprocess.run(
            [sys.executable, "-m", "picblobs_cli", "--help"],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )
        assert r.returncode == 0
        assert "picblobs-cli" in r.stdout


# ---------------------------------------------------------------------------
# 12.3 list-runners
# ---------------------------------------------------------------------------


class TestListRunners:
    def test_lists_all_runners(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["list-runners"])
        assert r.exit_code == 0
        # At least linux + freebsd + windows entries.
        for kind in ("linux", "freebsd", "windows"):
            assert kind in r.output

    def test_os_filter_limits_output(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["list-runners", "--os", "linux"])
        assert r.exit_code == 0
        assert "linux" in r.output
        # With filter, non-linux runners shouldn't show as rows (the header
        # mentions RUNNER/ARCH/PATH but those aren't runner types).
        lines = [
            line
            for line in r.output.splitlines()
            if line and not line.startswith(("RUNNER", "-"))
        ]
        for line in lines:
            assert line.startswith("linux"), line

    def test_arch_filter(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["list-runners", "--arch", "x86_64"])
        assert r.exit_code == 0

    def test_bogus_filter_fails_clean(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["list-runners", "--os", "nonesuch"])
        assert r.exit_code != 0


# ---------------------------------------------------------------------------
# 12.4 / 12.5 Build command — parity with builder API
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_alloc_jump_parity(self, runner: CliRunner, tmp_path: Path) -> None:
        payload = b"CAFEBABE" * 4
        payload_file = tmp_path / "payload.bin"
        payload_file.write_bytes(payload)
        out_file = tmp_path / "out.bin"

        r = runner.invoke(
            main,
            [
                "build",
                "alloc_jump",
                "linux:x86_64",
                "--payload",
                str(payload_file),
                "-o",
                str(out_file),
            ],
        )
        assert r.exit_code == 0, r.output

        expected = (
            picblobs.Blob("linux", "x86_64").alloc_jump().payload(payload).build()
        )
        assert out_file.read_bytes() == expected

    def test_stager_tcp_parity(self, runner: CliRunner, tmp_path: Path) -> None:
        out_file = tmp_path / "stg.bin"
        r = runner.invoke(
            main,
            [
                "build",
                "stager_tcp",
                "linux:aarch64",
                "--address",
                "10.0.0.1",
                "--port",
                "4444",
                "-o",
                str(out_file),
            ],
        )
        assert r.exit_code == 0, r.output

        expected = (
            picblobs.Blob("linux", "aarch64")
            .stager_tcp()
            .address("10.0.0.1")
            .port(4444)
            .build()
        )
        assert out_file.read_bytes() == expected

    def test_stager_fd(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "fd.bin"
        r = runner.invoke(
            main,
            [
                "build",
                "stager_fd",
                "linux:x86_64",
                "--fd",
                "3",
                "-o",
                str(out),
            ],
        )
        assert r.exit_code == 0
        expected = picblobs.Blob("linux", "x86_64").stager_fd().fd(3).build()
        assert out.read_bytes() == expected

    def test_stager_pipe(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "pipe.bin"
        r = runner.invoke(
            main,
            [
                "build",
                "stager_pipe",
                "linux:x86_64",
                "--path",
                "/tmp/my.fifo",
                "-o",
                str(out),
            ],
        )
        assert r.exit_code == 0
        expected = (
            picblobs.Blob("linux", "x86_64").stager_pipe().path("/tmp/my.fifo").build()
        )
        assert out.read_bytes() == expected

    def test_stager_mmap(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "mmap.bin"
        r = runner.invoke(
            main,
            [
                "build",
                "stager_mmap",
                "linux:x86_64",
                "--path",
                "/tmp/x",
                "--size",
                "64",
                "-o",
                str(out),
            ],
        )
        assert r.exit_code == 0
        expected = (
            picblobs.Blob("linux", "x86_64")
            .stager_mmap()
            .path("/tmp/x")
            .size(64)
            .build()
        )
        assert out.read_bytes() == expected

    def test_reflective_pe(self, runner: CliRunner, tmp_path: Path) -> None:
        pe_file = tmp_path / "dummy.pe"
        dummy = b"MZ" + b"\x00" * 126
        pe_file.write_bytes(dummy)
        out = tmp_path / "refl.bin"
        r = runner.invoke(
            main,
            [
                "build",
                "reflective_pe",
                "windows:x86_64",
                "--pe",
                str(pe_file),
                "-o",
                str(out),
            ],
        )
        assert r.exit_code == 0
        expected = picblobs.Blob("windows", "x86_64").reflective_pe().pe(dummy).build()
        assert out.read_bytes() == expected

    def test_hello_windows(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "hello_windows.bin"
        r = runner.invoke(
            main,
            [
                "build",
                "hello_windows",
                "windows:x86_64",
                "-o",
                str(out),
            ],
        )
        assert r.exit_code == 0, r.output
        expected = picblobs.Blob("windows", "x86_64").hello_windows().build()
        assert out.read_bytes() == expected

    # --- Negative / validation ---

    def test_hello_rejects_unrelated_option(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        r = runner.invoke(
            main,
            [
                "build",
                "hello",
                "linux:x86_64",
                "--address",
                "1.2.3.4",
                "-o",
                str(tmp_path / "x.bin"),
            ],
        )
        assert r.exit_code != 0
        assert "not valid for this blob type" in r.output

    def test_missing_required_payload(self, runner: CliRunner, tmp_path: Path) -> None:
        r = runner.invoke(
            main,
            [
                "build",
                "alloc_jump",
                "linux:x86_64",
                "-o",
                str(tmp_path / "x.bin"),
            ],
        )
        assert r.exit_code != 0
        assert "requires --payload" in r.output

    def test_missing_port(self, runner: CliRunner, tmp_path: Path) -> None:
        r = runner.invoke(
            main,
            [
                "build",
                "stager_tcp",
                "linux:x86_64",
                "--address",
                "1.2.3.4",
                "-o",
                str(tmp_path / "x.bin"),
            ],
        )
        assert r.exit_code != 0

    def test_unsupported_os(self, runner: CliRunner, tmp_path: Path) -> None:
        r = runner.invoke(
            main,
            [
                "build",
                "hello",
                "macos:x86_64",
                "-o",
                str(tmp_path / "x.bin"),
            ],
        )
        assert r.exit_code != 0

    def test_invalid_target_format(self, runner: CliRunner, tmp_path: Path) -> None:
        r = runner.invoke(
            main,
            [
                "build",
                "hello",
                "linux_x86_64",  # missing colon
                "-o",
                str(tmp_path / "x.bin"),
            ],
        )
        assert r.exit_code != 0

    def test_reflective_pe_not_on_linux(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        pe_file = tmp_path / "x.pe"
        pe_file.write_bytes(b"MZ" + b"\x00" * 126)
        r = runner.invoke(
            main,
            [
                "build",
                "reflective_pe",
                "linux:x86_64",
                "--pe",
                str(pe_file),
                "-o",
                str(tmp_path / "out.bin"),
            ],
        )
        assert r.exit_code != 0


# ---------------------------------------------------------------------------
# 12.7 Run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_hello_native(self, runner: CliRunner, qemu_available: bool) -> None:
        _require_qemu(qemu_available)
        r = runner.invoke(main, ["run", "hello", "linux:x86_64"])
        assert r.exit_code == 0
        assert "Hello, world!" in r.output

    def test_hello_cross_arch(self, runner: CliRunner, qemu_available: bool) -> None:
        _require_qemu(qemu_available)
        r = runner.invoke(main, ["run", "hello", "linux:aarch64"])
        assert r.exit_code == 0
        assert "Hello, world!" in r.output

    def test_nonexistent_blob(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["run", "nonexistent", "linux:x86_64"])
        assert r.exit_code != 0
        assert "No blob" in r.output

    def test_invalid_target(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["run", "hello", "bogus_target"])
        assert r.exit_code != 0

    def test_stdin_piping(
        self,
        runner: CliRunner,
        qemu_available: bool,
        tmp_path: Path,
    ) -> None:
        """stager_fd reads a length-prefixed payload from stdin."""
        _require_qemu(qemu_available)
        inner = picblobs.get_blob("test_fd_ok", "linux", "x86_64").code

        stdin_file = tmp_path / "stdin.bin"
        stdin_file.write_bytes(struct.pack("<I", len(inner)) + inner)

        config_file = tmp_path / "cfg.bin"
        config_file.write_bytes(struct.pack("<I", 0))

        r = runner.invoke(
            main,
            [
                "run",
                "stager_fd",
                "linux:x86_64",
                "--payload",
                str(config_file),
                "--stdin",
                str(stdin_file),
            ],
        )
        assert r.exit_code == 0, r.output
        assert "FD_OK" in r.output


# ---------------------------------------------------------------------------
# 12.7a Run command — --file (from-disk) mode
# ---------------------------------------------------------------------------


class TestRunFromFile:
    """run --file: execute an already-assembled blob straight from disk."""

    def _build_alloc_jump(
        self, runner: CliRunner, tmp_path: Path, arch: str = "x86_64"
    ) -> Path:
        """Helper: build alloc_jump+test_pass and return the output path."""
        inner_code = picblobs.get_blob("test_pass", "linux", arch).code
        payload_file = tmp_path / f"inner_{arch}.bin"
        payload_file.write_bytes(inner_code)
        out_file = tmp_path / f"aj_{arch}.bin"
        r = runner.invoke(
            main,
            [
                "build",
                "alloc_jump",
                f"linux:{arch}",
                "--payload",
                str(payload_file),
                "-o",
                str(out_file),
            ],
        )
        assert r.exit_code == 0, r.output
        return out_file

    def test_run_file_native(
        self,
        runner: CliRunner,
        qemu_available: bool,
        tmp_path: Path,
    ) -> None:
        _require_qemu(qemu_available)
        blob = self._build_alloc_jump(runner, tmp_path, "x86_64")
        r = runner.invoke(
            main,
            [
                "run",
                "--file",
                str(blob),
                "linux:x86_64",
            ],
        )
        assert r.exit_code == 0, r.output
        assert "PASS" in r.output

    def test_run_file_cross_arch(
        self,
        runner: CliRunner,
        qemu_available: bool,
        tmp_path: Path,
    ) -> None:
        """Cross-arch dispatch via QEMU works for files from disk."""
        _require_qemu(qemu_available)
        blob = self._build_alloc_jump(runner, tmp_path, "aarch64")
        r = runner.invoke(
            main,
            [
                "run",
                "--file",
                str(blob),
                "linux:aarch64",
            ],
        )
        assert r.exit_code == 0, r.output
        assert "PASS" in r.output

    def test_run_file_parity_with_registry(
        self,
        runner: CliRunner,
        qemu_available: bool,
        tmp_path: Path,
    ) -> None:
        """A blob assembled via `build` and run via `--file` produces the
        same stdout / exit code as the registry-mode path with the
        equivalent config."""
        _require_qemu(qemu_available)

        blob_file = self._build_alloc_jump(runner, tmp_path, "x86_64")
        r_file = runner.invoke(
            main,
            [
                "run",
                "--file",
                str(blob_file),
                "linux:x86_64",
            ],
        )

        inner = picblobs.get_blob("test_pass", "linux", "x86_64").code
        cfg_file = tmp_path / "aj_cfg.bin"
        cfg_file.write_bytes(struct.pack("<I", len(inner)) + inner)
        r_registry = runner.invoke(
            main,
            [
                "run",
                "alloc_jump",
                "linux:x86_64",
                "--payload",
                str(cfg_file),
            ],
        )

        assert r_file.exit_code == r_registry.exit_code == 0
        assert r_file.stdout == r_registry.stdout

    def test_file_and_blob_type_mutually_exclusive(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        fake = tmp_path / "empty.bin"
        fake.write_bytes(b"\x00" * 16)
        r = runner.invoke(
            main,
            [
                "run",
                "hello",
                "linux:x86_64",
                "--file",
                str(fake),
            ],
        )
        assert r.exit_code != 0
        assert "--file" in r.output

    def test_config_hex_rejected_in_file_mode(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        fake = tmp_path / "empty.bin"
        fake.write_bytes(b"\x00" * 16)
        r = runner.invoke(
            main,
            [
                "run",
                "--file",
                str(fake),
                "linux:x86_64",
                "--config-hex",
                "00",
            ],
        )
        assert r.exit_code != 0

    def test_payload_rejected_in_file_mode(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        fake = tmp_path / "empty.bin"
        fake.write_bytes(b"\x00" * 16)
        stray = tmp_path / "stray.bin"
        stray.write_bytes(b"X")
        r = runner.invoke(
            main,
            [
                "run",
                "--file",
                str(fake),
                "linux:x86_64",
                "--payload",
                str(stray),
            ],
        )
        assert r.exit_code != 0

    def test_missing_file(self, runner: CliRunner, tmp_path: Path) -> None:
        r = runner.invoke(
            main,
            [
                "run",
                "--file",
                str(tmp_path / "does_not_exist.bin"),
                "linux:x86_64",
            ],
        )
        assert r.exit_code != 0

    def test_file_mode_needs_target(self, runner: CliRunner, tmp_path: Path) -> None:
        fake = tmp_path / "empty.bin"
        fake.write_bytes(b"\x00" * 16)
        r = runner.invoke(main, ["run", "--file", str(fake)])
        assert r.exit_code != 0

    def test_registry_mode_needs_two_positionals(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["run", "hello"])
        assert r.exit_code != 0

    def test_file_mode_stdin_piping(
        self,
        runner: CliRunner,
        qemu_available: bool,
        tmp_path: Path,
    ) -> None:
        """--stdin still works in file mode: build a stager_fd, feed it
        a length-prefixed inner payload on stdin."""
        _require_qemu(qemu_available)
        inner = picblobs.get_blob("test_fd_ok", "linux", "x86_64").code

        stage = tmp_path / "stage.bin"
        rb = runner.invoke(
            main,
            [
                "build",
                "stager_fd",
                "linux:x86_64",
                "--fd",
                "0",
                "-o",
                str(stage),
            ],
        )
        assert rb.exit_code == 0, rb.output

        stdin_file = tmp_path / "stdin.bin"
        stdin_file.write_bytes(struct.pack("<I", len(inner)) + inner)

        r = runner.invoke(
            main,
            [
                "run",
                "--file",
                str(stage),
                "linux:x86_64",
                "--stdin",
                str(stdin_file),
            ],
        )
        assert r.exit_code == 0, r.output
        assert "FD_OK" in r.output


# ---------------------------------------------------------------------------
# 12.8 Verify command
# ---------------------------------------------------------------------------


class TestVerifyCommand:
    @pytest.mark.timeout(60)
    def test_hello_only(self, runner: CliRunner, qemu_available: bool) -> None:
        _require_qemu(qemu_available)
        r = runner.invoke(main, ["verify", "--type", "hello", "--os", "linux"])
        assert r.exit_code == 0
        assert "passed" in r.output

    @pytest.mark.timeout(60)
    def test_type_and_os_filter(self, runner: CliRunner, qemu_available: bool) -> None:
        _require_qemu(qemu_available)
        r = runner.invoke(main, ["verify", "--type", "hello", "--os", "linux"])
        assert r.exit_code == 0
        # No freebsd output when --os filter is applied.
        assert "[freebsd]" not in r.output

    def test_verify_filters_freebsd_to_x86_64(self) -> None:
        from picblobs_cli.cli import _filter_verify_combos

        combos = [
            ("hello", "freebsd", "aarch64"),
            ("hello", "freebsd", "x86_64"),
            ("ul_exec", "freebsd", "x86_64"),
            ("hello", "linux", "x86_64"),
        ]
        assert _filter_verify_combos(combos, (), (), ()) == [
            ("hello", "freebsd", "x86_64"),
            ("hello", "linux", "x86_64"),
        ]

    def test_windows_stager_fd_uses_hello_windows_inner_blob(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from picblobs_cli import cli

        calls: list[tuple[str, str, str]] = []

        def _get_blob(blob_type: str, os_name: str, arch: str):
            calls.append((blob_type, os_name, arch))
            return SimpleNamespace(code=b"HELLO", blob_type=blob_type)

        monkeypatch.setattr(cli.picblobs, "get_blob", _get_blob)
        monkeypatch.setattr(
            cli,
            "run_blob",
            lambda *args, **kwargs: SimpleNamespace(
                stdout=b"Hello, world!", stderr=b"", exit_code=0
            ),
        )

        result = cli._verify_stager_fd("windows", "x86_64", 30.0)
        assert result.exit_code == 0
        assert calls == [
            ("hello_windows", "windows", "x86_64"),
            ("stager_fd", "windows", "x86_64"),
        ]

    def test_no_matches(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["verify", "--type", "nothing_matches"])
        assert r.exit_code != 0


# ---------------------------------------------------------------------------
# 12.9 Runner discovery contract
# ---------------------------------------------------------------------------


class TestRunnerDiscovery:
    def test_prefers_picblobs_cli_bundle(self) -> None:
        from picblobs.runner import find_runner

        p = find_runner("linux", "x86_64")
        # Path points inside picblobs_cli/_runners.
        assert "/picblobs_cli/_runners/" in str(p), p

    def test_error_mentions_picblobs_cli(self, tmp_path: Path) -> None:
        """With every discovery path neutered, the error SHALL name the package."""
        from picblobs.runner import find_runner

        # Use a runner_type that doesn't exist in the bundle and an empty
        # search_paths to bypass both sources.
        with pytest.raises(FileNotFoundError) as exc:
            find_runner(
                "not_a_real_os",
                "not_an_arch",
                search_paths=[tmp_path],
            )
        assert "picblobs-cli" in str(exc.value)


# ---------------------------------------------------------------------------
# 12.10 Wheel purity: picblobs no longer ships runners
# ---------------------------------------------------------------------------


class TestPicblobsWheelPurity:
    def test_no_runners_dir_inside_picblobs(self) -> None:
        picblobs_pkg_dir = Path(picblobs.__file__).parent
        bad = picblobs_pkg_dir / "_runners"
        assert not bad.exists(), (
            f"{bad} should not exist — runners live in picblobs-cli now"
        )

    def test_picblobs_still_works_on_its_own(self) -> None:
        """Basic picblobs.Blob().build() works without touching the runner bundle."""
        out = picblobs.Blob("linux", "x86_64").alloc_jump().payload(b"x").build()
        assert isinstance(out, bytes) and len(out) > 0


# ---------------------------------------------------------------------------
# 12.11 info
# ---------------------------------------------------------------------------


class TestInfo:
    def test_info_prints_versions(self, runner: CliRunner) -> None:
        r = runner.invoke(main, ["info"])
        assert r.exit_code == 0
        assert "picblobs:" in r.output
        assert "picblobs-cli:" in r.output
        assert "runner bundle:" in r.output
        assert "Targets:" in r.output
