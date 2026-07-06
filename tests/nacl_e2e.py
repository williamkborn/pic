"""End-to-end NaCl encrypted handshake test for Bazel.

The test runs server and client PIC blobs under a declared QEMU binary. The
input blobs carry a default config, so each test copies them to a temp
directory and patches the config bytes to use an ephemeral localhost port.
"""

from __future__ import annotations

import hashlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXPECTED_MSG = b"Hello from NaCl PIC blob!"
READY_MARKER = b"[server] listening\n"
AUTH_KEY = bytes(range(1, 33))
DEFAULT_CONFIG = b"\x0f\x27" + (b"\x00" * 32)
PROCESS_TIMEOUT = 30.0
READY_TIMEOUT = 10.0


def _reserve_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _configured_blob(src: Path, dst_dir: Path, port: int) -> Path:
    data = src.read_bytes()
    config = struct.pack("<H", port) + AUTH_KEY
    matches = data.count(DEFAULT_CONFIG)
    if matches != 1:
        raise RuntimeError(
            f"{src}: expected one default NaCl config block, found {matches}",
        )
    dst = dst_dir / src.name
    dst.write_bytes(data.replace(DEFAULT_CONFIG, config, 1))
    dst.chmod(0o755)
    return dst


def _wait_for_ready(proc: subprocess.Popen[bytes], output: Path) -> None:
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        if output.exists() and READY_MARKER in output.read_bytes():
            return
        if proc.poll() is not None:
            raise RuntimeError(
                f"server exited before listening with status {proc.returncode}",
            )
        time.sleep(0.05)
    raise RuntimeError("server did not reach listening state")


def _read(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def _run_pair(qemu: Path, runner: Path, server_bin: Path, client_bin: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="picblobs-nacl-") as tmp_raw:
        tmp = Path(tmp_raw)
        port = _reserve_tcp_port()
        server = _configured_blob(server_bin, tmp, port)
        client = _configured_blob(client_bin, tmp, port)
        server_out = tmp / "server.out"
        client_out = tmp / "client.out"

        with server_out.open("wb") as server_stdout:
            server_proc = subprocess.Popen(
                [str(qemu), str(runner), str(server)],
                stdout=server_stdout,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_for_ready(server_proc, server_out)
                client_result = subprocess.run(
                    [str(qemu), str(runner), str(client)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=PROCESS_TIMEOUT,
                )
                client_out.write_bytes(client_result.stdout)
                try:
                    server_exit = server_proc.wait(timeout=PROCESS_TIMEOUT)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
                    server_exit = server_proc.wait()
                    raise RuntimeError("server timed out") from None
            finally:
                if server_proc.poll() is None:
                    server_proc.kill()
                    server_proc.wait()

        server_bytes = _read(server_out)
        client_bytes = _read(client_out)
        sys.stdout.write("--- Server output ---\n")
        sys.stdout.buffer.write(server_bytes)
        sys.stdout.write("--- Client output ---\n")
        sys.stdout.buffer.write(client_bytes)

        failed = False
        if server_exit != 0:
            sys.stderr.write(f"FAIL: server exited {server_exit}\n")
            failed = True
        if client_result.returncode != 0:
            sys.stderr.write(f"FAIL: client exited {client_result.returncode}\n")
            failed = True
        if EXPECTED_MSG not in server_bytes:
            sys.stderr.write("FAIL: server did not print decrypted message\n")
            failed = True
        else:
            digest = hashlib.sha256(EXPECTED_MSG).hexdigest()
            sys.stdout.write(f"OK: payload SHA256 match ({digest})\n")
        if b"secure channel OK" not in server_bytes:
            sys.stderr.write("FAIL: server did not confirm secure channel\n")
            failed = True
        if b"secure channel OK" not in client_bytes:
            sys.stderr.write("FAIL: client did not confirm secure channel\n")
            failed = True
        return 1 if failed else 0


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        sys.stderr.write(
            "Usage: nacl_e2e.py <qemu> <runner> <server.bin> <client.bin>\n",
        )
        return 2
    return _run_pair(*(Path(arg) for arg in argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
