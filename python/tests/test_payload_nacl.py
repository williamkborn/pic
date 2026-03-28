"""Payload tests for NaCl crypto blobs.

- nacl_hello: standalone self-test (encrypt/decrypt round-trip)
- nacl_client + nacl_server: paired e2e encrypted TCP handshake

See: spec/verification/TEST-011-payload-pytest-suite.md
"""

from __future__ import annotations

import subprocess
import time

import pytest

from picblobs import get_blob
from picblobs.runner import (
    find_qemu,
    find_runner,
    is_arch_skip_rosetta,
    prepare_blob,
    run_blob,
    _build_command,
    _cleanup_blob_file,
)

from payload_defs import EXPECTATIONS, OPERATING_SYSTEMS, PAYLOAD_PLATFORMS, RUNNER_TYPE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nacl_combos() -> list[tuple[str, str, str]]:
    """Return (blob_type, os, arch) for nacl_hello."""
    combos = []
    for os_name in PAYLOAD_PLATFORMS.get("nacl_hello", []):
        os_entry = OPERATING_SYSTEMS.get(os_name)
        if os_entry is None:
            continue
        for arch in os_entry.architectures:
            combos.append(("nacl_hello", os_name, arch))
    return sorted(combos)


def _e2e_combos() -> list[tuple[str, str]]:
    """Return (os, arch) combos where both nacl_client and nacl_server can run."""
    combos = []
    for os_name in PAYLOAD_PLATFORMS.get("nacl_hello", []):
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


# ---------------------------------------------------------------------------
# nacl_hello: standalone self-test
# ---------------------------------------------------------------------------


class TestNaClPayload:
    """Run nacl_hello on every supported platform."""

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize(
        "blob_type,target_os,target_arch",
        _nacl_combos(),
        ids=[f"{bt}:{os}:{arch}" for bt, os, arch in _nacl_combos()],
    )
    def test_nacl_hello_selftest(
        self,
        blob_type: str,
        target_os: str,
        target_arch: str,
    ) -> None:
        if not _blob_exists(blob_type, target_os, target_arch):
            pytest.skip(f"Blob not staged: {blob_type}/{target_os}/{target_arch}")

        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        runner_type = RUNNER_TYPE[target_os]
        try:
            find_runner(runner_type, target_arch)
        except FileNotFoundError:
            pytest.skip(f"No {runner_type} runner for {target_arch}")

        exp = EXPECTATIONS[blob_type]
        blob = get_blob(blob_type, target_os, target_arch)
        result = run_blob(blob, timeout=exp.timeout)

        assert result.exit_code == exp.exit_code, (
            f"{blob_type} {target_os}:{target_arch}: "
            f"exit_code={result.exit_code}, expected={exp.exit_code}, "
            f"stderr={result.stderr!r}"
        )
        assert result.stdout == exp.stdout, (
            f"{blob_type} {target_os}:{target_arch}: "
            f"stdout={result.stdout!r}, expected={exp.stdout!r}"
        )


# ---------------------------------------------------------------------------
# nacl_client + nacl_server: paired e2e test
# ---------------------------------------------------------------------------

EXPECTED_PLAINTEXT = b"Hello from NaCl PIC blob!"
E2E_TIMEOUT = 30.0
NACL_PORT = 9999

_E2E_SKIP_ARCHES: frozenset[str] = frozenset()
_SERVER_STARTUP = 0.5


class TestNaClE2E:
    """Run nacl_server + nacl_client in parallel on each architecture.

    Protocol:
      1. Server binds 0.0.0.0:9999, accepts one connection.
      2. Client connects to 127.0.0.1:9999, sends encrypted message.
      3. Server decrypts, prints plaintext, sends encrypted ACK.
      4. Client decrypts ACK, both exit 0.
    """

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize(
        "target_os,target_arch",
        _e2e_combos(),
        ids=[f"{os}:{arch}" for os, arch in _e2e_combos()],
    )
    def test_nacl_e2e_handshake(
        self,
        target_os: str,
        target_arch: str,
    ) -> None:
        # Skip if blobs not staged.
        for bt in ("nacl_server", "nacl_client"):
            if not _blob_exists(bt, target_os, target_arch):
                pytest.skip(f"Blob not staged: {bt}/{target_os}/{target_arch}")

        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        # Port 9999 is hardcoded in the NaCl C sources. Skip if already bound.
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", NACL_PORT)) == 0:
                pytest.skip(f"Port {NACL_PORT} in use (another NaCl test running?)")

        runner_type = RUNNER_TYPE[target_os]
        try:
            runner_path = find_runner(runner_type, target_arch)
        except FileNotFoundError:
            pytest.skip(f"No {runner_type} runner for {target_arch}")

        server_blob = get_blob("nacl_server", target_os, target_arch)
        client_blob = get_blob("nacl_client", target_os, target_arch)

        if target_arch in _E2E_SKIP_ARCHES:
            pytest.skip(
                f"QEMU {target_arch} too slow for NaCl e2e handshake "
                f"(crypto proven by nacl_hello)"
            )

        server_bin = prepare_blob(server_blob)
        client_bin = prepare_blob(client_blob)

        try:
            server_cmd = _build_command(runner_path, server_bin, target_arch)
            client_cmd = _build_command(runner_path, client_bin, target_arch)

            # Launch server first.
            server_proc = subprocess.Popen(
                server_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Give server time to bind.
            time.sleep(_SERVER_STARTUP)

            # Launch client.
            client_proc = subprocess.Popen(
                client_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for client to finish (it drives the protocol).
            client_stdout, client_stderr = client_proc.communicate(
                timeout=E2E_TIMEOUT
            )
            client_exit = client_proc.returncode

            # Server should exit shortly after client disconnects.
            server_stdout, server_stderr = server_proc.communicate(
                timeout=E2E_TIMEOUT
            )
            server_exit = server_proc.returncode

        except subprocess.TimeoutExpired:
            server_proc.kill()
            client_proc.kill()
            server_proc.wait()
            client_proc.wait()
            pytest.fail(
                f"NaCl e2e timed out on {target_os}:{target_arch} "
                f"(timeout={E2E_TIMEOUT}s)\n"
                f"  server stderr: {server_proc.stderr.read()!r}\n"
                f"  client stderr: {client_proc.stderr.read()!r}"
            )
        finally:
            _cleanup_blob_file(server_bin)
            _cleanup_blob_file(client_bin)

        # Both must exit 0.
        assert server_exit == 0, (
            f"server {target_os}:{target_arch}: exit={server_exit}\n"
            f"  stdout: {server_stdout!r}\n  stderr: {server_stderr!r}"
        )
        assert client_exit == 0, (
            f"client {target_os}:{target_arch}: exit={client_exit}\n"
            f"  stdout: {client_stdout!r}\n  stderr: {client_stderr!r}"
        )

        # Server must have decrypted the expected plaintext.
        assert EXPECTED_PLAINTEXT in server_stdout, (
            f"server {target_os}:{target_arch}: plaintext not found in output\n"
            f"  stdout: {server_stdout!r}"
        )

        # Both must confirm secure channel.
        assert b"secure channel OK" in server_stdout, (
            f"server {target_os}:{target_arch}: no channel confirmation\n"
            f"  stdout: {server_stdout!r}"
        )
        assert b"secure channel OK" in client_stdout, (
            f"client {target_os}:{target_arch}: no channel confirmation\n"
            f"  stdout: {client_stdout!r}"
        )
