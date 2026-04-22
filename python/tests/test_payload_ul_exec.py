"""Payload tests for ul_exec (userland exec) blob.

ul_exec loads an ELF binary from its config buffer and executes it
without using execve(). Tests verify both static and dynamically
linked ELFs.

See: spec/verification/TEST-011-payload-pytest-suite.md
"""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from picblobs import get_blob
from picblobs._cross_compile import find_gcc
from picblobs.runner import is_arch_skip_rosetta, run_blob, find_runner

from payload_defs import OPERATING_SYSTEMS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Map our arch names to GCC cross-compiler triples used by Bootlin toolchains.
ARCH_TO_TRIPLE = {
    "x86_64": "x86_64-buildroot-linux-gnu",
    "i686": "i686-buildroot-linux-gnu",
    "aarch64": "aarch64-buildroot-linux-gnu",
    "armv5_arm": "arm-buildroot-linux-gnueabi",
    "armv5_thumb": "arm-buildroot-linux-gnueabi",
    "armv7_thumb": "arm-buildroot-linux-gnueabihf",
    "mipsel32": "mipsel-buildroot-linux-gnu",
    "mipsbe32": "mips-buildroot-linux-gnu",
    "s390x": "s390x-buildroot-linux-gnu",
    "sparcv8": "sparc-buildroot-linux-uclibc",
    "powerpc": "powerpc-buildroot-linux-gnu",
    "ppc64le": "powerpc64le-buildroot-linux-gnu",
    "riscv64": "riscv64-buildroot-linux-gnu",
}

# Extra cflags for specific arches.
ARCH_EXTRA_CFLAGS = {
    "armv5_thumb": ["-mthumb"],
    "armv7_thumb": ["-march=armv7-a", "-mthumb"],
    "powerpc": ["-mcpu=e300c3"],
    "ppc64le": ["-mcpu=power8"],
}

# Bazel external toolchain base path.
BOOTLIN_BASE = Path("bazel-out/../external").resolve()

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _find_sysroot(arch: str) -> str | None:
    """Find the Bootlin sysroot for an architecture."""
    triple = ARCH_TO_TRIPLE.get(arch)
    bootlin_arch_map = {
        "x86_64": "x86_64",
        "i686": "i686",
        "aarch64": "aarch64",
        "armv5_arm": "armv5",
        "armv5_thumb": "armv5",
        "armv7_thumb": "armv7",
        "mipsel32": "mipsel32",
        "mipsbe32": "mipsbe32",
        "s390x": "s390x",
        "sparcv8": "sparcv8",
        "powerpc": "powerpc",
        "ppc64le": "ppc64le",
        "riscv64": "riscv64",
    }
    bootlin_name = bootlin_arch_map.get(arch)
    if not bootlin_name or not triple:
        return None

    try:
        res = subprocess.run(
            ["bazel", "info", "output_base"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        if res.returncode == 0:
            output_base = Path(res.stdout.strip())
            candidates = [
                output_base
                / "external"
                / f"+bootlin+bootlin_{bootlin_name}"
                / f"{triple}"
                / "sysroot",
                PROJECT_ROOT
                / "bazel-pic"
                / "external"
                / f"+bootlin+bootlin_{bootlin_name}"
                / f"{triple}"
                / "sysroot",
            ]
            for sysroot in candidates:
                if sysroot.exists():
                    return str(sysroot)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    fallback = (
        PROJECT_ROOT
        / "bazel-pic"
        / "external"
        / f"+bootlin+bootlin_{bootlin_name}"
        / f"{triple}"
        / "sysroot"
    )
    if fallback.exists():
        return str(fallback)
    return None


def _blob_exists(blob_type: str, target_os: str, target_arch: str) -> bool:
    try:
        get_blob(blob_type, target_os, target_arch)
        return True
    except FileNotFoundError:
        return False


def _compile_test_elf(
    arch: str,
    source: str,
    static: bool = True,
    extra_cflags: list[str] | None = None,
) -> bytes | None:
    """Compile a C program to an ELF binary using the Bootlin cross-compiler.

    Returns the ELF binary as bytes, or None if compiler not found.
    """
    gcc = find_gcc(arch)
    if gcc is None:
        return None

    sysroot = _find_sysroot(arch)

    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = Path(tmpdir) / "test.c"
        out_path = Path(tmpdir) / "test.elf"
        src_path.write_text(source)

        cmd = [gcc]
        if sysroot:
            cmd.append(f"--sysroot={sysroot}")
        cmd.extend([str(src_path), "-o", str(out_path), "-O2"])
        if static:
            cmd.append("-static")
        if extra_cflags:
            cmd.extend(extra_cflags)
        arch_flags = ARCH_EXTRA_CFLAGS.get(arch, [])
        cmd.extend(arch_flags)

        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            return None

        return out_path.read_bytes()


def _compile_raw_elf(arch: str, pie: bool = False) -> bytes | None:
    """Compile an arch-specific raw syscall asm program (no libc).

    If pie=True, compile as position-independent (ET_DYN).
    Otherwise compile as static (ET_EXEC) — may conflict with QEMU
    on some architectures.

    Returns the ELF binary as bytes, or None if not supported.
    """
    asm_src = RAW_SYSCALL_SRCS.get(arch)
    if asm_src is None:
        return None

    gcc = find_gcc(arch)
    if gcc is None:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = Path(tmpdir) / "test.S"
        out_path = Path(tmpdir) / "test.elf"
        src_path.write_text(asm_src)

        cmd = [gcc, str(src_path), "-o", str(out_path), "-nostdlib", "-nostartfiles"]
        if pie:
            # -shared produces ET_DYN without PT_INTERP (no ld-linux needed).
            cmd.extend(["-shared", "-Wl,-e,_start"])
        else:
            cmd.append("-static")
        arch_flags = ARCH_EXTRA_CFLAGS.get(arch, [])
        cmd.extend(arch_flags)

        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            return None

        return out_path.read_bytes()


# Architectures that are big-endian.
_BIG_ENDIAN_ARCHES = {"mipsbe32", "s390x", "sparcv8", "powerpc"}


def _build_ul_exec_config(
    elf_data: bytes,
    argv: list[str] | None = None,
    envp: list[str] | None = None,
    target_arch: str = "x86_64",
) -> bytes:
    """Build the config struct for ul_exec."""
    if argv is None:
        argv = ["test"]
    if envp is None:
        envp = []

    # Null-separated argv strings.
    argv_data = b""
    for a in argv:
        argv_data += a.encode() + b"\x00"

    # Null-separated envp strings.
    envp_data = b""
    for e in envp:
        envp_data += e.encode() + b"\x00"

    # Pack header in target-native byte order.
    endian = ">" if target_arch in _BIG_ENDIAN_ARCHES else "<"
    header = struct.pack(
        f"{endian}IIIII",
        len(elf_data),
        len(argv),
        len(argv_data),
        len(envp),
        len(envp_data),
    )
    return header + elf_data + argv_data + envp_data


# ---------------------------------------------------------------------------
# Test ELF source code — uses libc for convenience.
# ---------------------------------------------------------------------------

# Static test: uses libc. Compiled with -static.
STATIC_LIBC_SRC = '#include <unistd.h>\n#include <string.h>\nint main(void) {\n    const char msg[] = "UL_EXEC_OK\\n";\n    write(1, msg, strlen(msg));\n    return 0;\n}\n'

# Dynamic test (x86_64 only): same source, no -static.
DYNAMIC_TEST_SRC = STATIC_LIBC_SRC

# Raw syscall test: no libc. Works on all arches.
# Each arch needs its own _start because syscall ABI differs.
# Raw syscall test programs. Must work both as non-PIE (ET_EXEC) and
# as PIE (ET_DYN). Use PC-relative addressing where possible; on arches
# without it, embed the string in .text right after the code.
RAW_SYSCALL_SRCS = {
    "x86_64": (
        ".text\n.globl _start\n_start:\n"
        "  mov $1, %eax\n  mov $1, %edi\n  lea msg(%rip), %rsi\n"
        "  mov $11, %edx\n  syscall\n"
        "  mov $231, %eax\n  xor %edi, %edi\n  syscall\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "i686": (
        # i686: no RIP-relative. Use call/pop to get PC, then add offset.
        ".text\n.globl _start\n_start:\n"
        "  call 1f\n"
        "1: pop %ecx\n"
        "  add $(msg - 1b), %ecx\n"
        "  mov $4, %eax\n  mov $1, %ebx\n"
        "  mov $11, %edx\n  int $0x80\n"
        "  mov $252, %eax\n  xor %ebx, %ebx\n  int $0x80\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "aarch64": (
        ".text\n.globl _start\n_start:\n"
        "  mov x8, #64\n  mov x0, #1\n  adr x1, msg\n"
        "  mov x2, #11\n  svc #0\n"
        "  mov x8, #94\n  mov x0, #0\n  svc #0\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "armv5_arm": (
        ".text\n.globl _start\n_start:\n"
        "  mov r7, #4\n  mov r0, #1\n  adr r1, msg\n"
        "  mov r2, #11\n  svc #0\n"
        "  mov r7, #248\n  mov r0, #0\n  svc #0\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "armv5_thumb": (
        ".syntax unified\n.text\n.globl _start\n.thumb_func\n_start:\n"
        "  movs r7, #4\n  movs r0, #1\n  adr r1, msg\n"
        "  movs r2, #11\n  svc #0\n"
        "  movs r7, #248\n  movs r0, #0\n  svc #0\n"
        '.align 2\nmsg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    # armv7_thumb: Thumb-2 uses the same Thumb-1 encodings for these
    # instructions — reuse the armv5_thumb source.
    "armv7_thumb": (
        ".syntax unified\n.text\n.globl _start\n.thumb_func\n_start:\n"
        "  movs r7, #4\n  movs r0, #1\n  adr r1, msg\n"
        "  movs r2, #11\n  svc #0\n"
        "  movs r7, #248\n  movs r0, #0\n  svc #0\n"
        '.align 2\nmsg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "mipsel32": (
        # MIPS: embed string in .text, use bal to get PC.
        ".set noreorder\n.text\n.globl _start\n_start:\n"
        "  li $v0, 4004\n"
        "  li $a0, 1\n"
        "  bal 1f\n"
        "  li $a2, 11\n"  # delay slot
        "1: addiu $a1, $ra, (msg - 1b)\n"
        "  syscall\n"
        "  li $v0, 4246\n  li $a0, 0\n  syscall\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "mipsbe32": (
        ".set noreorder\n.text\n.globl _start\n_start:\n"
        "  li $v0, 4004\n"
        "  li $a0, 1\n"
        "  bal 1f\n"
        "  li $a2, 11\n"
        "1: addiu $a1, $ra, (msg - 1b)\n"
        "  syscall\n"
        "  li $v0, 4246\n  li $a0, 0\n  syscall\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "s390x": (
        ".text\n.globl _start\n_start:\n"
        "  lghi %r1, 4\n  lghi %r2, 1\n  larl %r3, msg\n"
        "  lghi %r4, 11\n  svc 0\n"
        "  lghi %r1, 248\n  lghi %r2, 0\n  svc 0\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "sparcv8": (
        ".text\n.globl _start\n_start:\n"
        "  mov 4, %g1\n"
        "  mov 1, %o0\n"
        "  sethi %hi(msg), %o1\n"
        "  or %o1, %lo(msg), %o1\n"
        "  mov 11, %o2\n"
        "  ta 0x10\n"
        "  nop\n"
        "  mov 188, %g1\n"
        "  clr %o0\n"
        "  ta 0x10\n"
        "  nop\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "powerpc": (
        ".text\n.globl _start\n_start:\n"
        "  li 0, 4\n"
        "  li 3, 1\n"
        "  lis 4, msg@ha\n"
        "  addi 4, 4, msg@l\n"
        "  li 5, 11\n"
        "  sc\n"
        "  li 0, 234\n"
        "  li 3, 0\n"
        "  sc\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "ppc64le": (
        ".text\n.globl _start\n_start:\n"
        "  li 0, 4\n"
        "  li 3, 1\n"
        "  bl 1f\n"
        "1: mflr 4\n"
        "  addi 4, 4, msg-1b\n"
        "  li 5, 11\n"
        "  sc\n"
        "  li 0, 234\n"
        "  li 3, 0\n"
        "  sc\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
    "riscv64": (
        ".text\n.globl _start\n_start:\n"
        "  li a7, 64\n"
        "  li a0, 1\n"
        "  la a1, msg\n"
        "  li a2, 11\n"
        "  ecall\n"
        "  li a7, 94\n"
        "  li a0, 0\n"
        "  ecall\n"
        'msg: .ascii "UL_EXEC_OK\\n"\n'
    ),
}


# ---------------------------------------------------------------------------
# Available architectures for ul_exec (linux only, excluding s390x).
# ---------------------------------------------------------------------------


def _ul_exec_arches() -> list[str]:
    """Arches where ul_exec is built and staged."""
    all_arches = OPERATING_SYSTEMS["linux"].architectures
    return [a for a in all_arches if _blob_exists("ul_exec", "linux", a)]


# ---------------------------------------------------------------------------
# Tests: static ELF execution
# ---------------------------------------------------------------------------


class TestUlExecStatic:
    """Test ul_exec with statically linked ELFs on all architectures.

    Uses raw syscall asm programs (no libc) for maximum compatibility.
    These are tiny non-PIE ET_EXEC binaries — the self-remap ensures
    the address space is clean before loading them.
    """

    @pytest.mark.requires_qemu
    @pytest.mark.parametrize("target_arch", _ul_exec_arches())
    def test_static_elf_executes(self, target_arch: str) -> None:
        """Load and execute a static non-PIE (ET_EXEC) raw-syscall ELF.

        The blob self-remaps to a safe high address, munmaps the
        target's load range, then MAP_FIXED loads the ELF at its
        fixed address. This is the full userland exec path.
        """
        if is_arch_skip_rosetta(target_arch):
            pytest.skip(f"QEMU {target_arch} crashes under Rosetta")

        try:
            find_runner("linux", target_arch)
        except FileNotFoundError:
            pytest.skip(f"No linux runner for {target_arch}")

        elf_data = _compile_raw_elf(target_arch, pie=False)
        if elf_data is None:
            pytest.skip(f"Cannot compile raw test ELF for {target_arch}")

        blob = get_blob("ul_exec", "linux", target_arch)
        config = _build_ul_exec_config(
            elf_data, argv=["test_static"], target_arch=target_arch
        )

        result = run_blob(blob, config=config, timeout=30.0)

        assert result.exit_code == 0, (
            f"ul_exec linux:{target_arch}: "
            f"exit_code={result.exit_code}, "
            f"stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        assert b"UL_EXEC_OK" in result.stdout, (
            f"ul_exec linux:{target_arch}: "
            f"stdout={result.stdout!r}, expected 'UL_EXEC_OK'"
        )

    @pytest.mark.requires_qemu
    def test_static_libc_elf_x86_64(self) -> None:
        """Static glibc binary on x86_64 (non-PIE, ET_EXEC)."""
        if not _blob_exists("ul_exec", "linux", "x86_64"):
            pytest.skip("ul_exec not staged for linux/x86_64")
        try:
            find_runner("linux", "x86_64")
        except FileNotFoundError:
            pytest.skip("No linux runner for x86_64")

        elf_data = _compile_test_elf("x86_64", STATIC_LIBC_SRC, static=True)
        if elf_data is None:
            pytest.skip("Cannot compile static libc ELF for x86_64")

        blob = get_blob("ul_exec", "linux", "x86_64")
        config = _build_ul_exec_config(elf_data, argv=["test_static_libc"])
        result = run_blob(blob, config=config, timeout=30.0)

        assert result.exit_code == 0, (
            f"exit_code={result.exit_code}, stderr={result.stderr!r}"
        )
        assert b"UL_EXEC_OK" in result.stdout


# ---------------------------------------------------------------------------
# Tests: dynamic ELF execution (x86_64 only)
# ---------------------------------------------------------------------------


class TestUlExecDynamic:
    """Test ul_exec with dynamically linked ELFs (x86_64 only)."""

    @pytest.mark.requires_qemu
    def test_dynamic_elf_executes_x86_64(self) -> None:
        if not _blob_exists("ul_exec", "linux", "x86_64"):
            pytest.skip("ul_exec not staged for linux/x86_64")

        try:
            find_runner("linux", "x86_64")
        except FileNotFoundError:
            pytest.skip("No linux runner for x86_64")

        elf_data = _compile_test_elf("x86_64", DYNAMIC_TEST_SRC, static=False)
        if elf_data is None:
            pytest.skip("Cannot compile dynamic test ELF for x86_64")

        blob = get_blob("ul_exec", "linux", "x86_64")
        config = _build_ul_exec_config(
            elf_data,
            argv=["test_dynamic"],
            envp=["PATH=/usr/bin", "HOME=/tmp"],
        )

        result = run_blob(blob, config=config, timeout=30.0)

        assert result.exit_code == 0, (
            f"ul_exec dynamic linux:x86_64: "
            f"exit_code={result.exit_code}, "
            f"stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        assert b"UL_EXEC_OK" in result.stdout


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestUlExecEdgeCases:
    """Error handling for ul_exec."""

    @pytest.mark.requires_qemu
    def test_invalid_elf_exits_cleanly(self) -> None:
        if not _blob_exists("ul_exec", "linux", "x86_64"):
            pytest.skip("ul_exec not staged for linux/x86_64")

        try:
            find_runner("linux", "x86_64")
        except FileNotFoundError:
            pytest.skip("No linux runner for x86_64")

        blob = get_blob("ul_exec", "linux", "x86_64")
        config = _build_ul_exec_config(b"\x00" * 64, argv=["bad"])

        result = run_blob(blob, config=config, timeout=10.0)
        # Should exit with error code 101 (bad ELF magic)
        assert result.exit_code != 0

    @pytest.mark.requires_qemu
    def test_truncated_elf_exits_cleanly(self) -> None:
        if not _blob_exists("ul_exec", "linux", "x86_64"):
            pytest.skip("ul_exec not staged for linux/x86_64")

        try:
            find_runner("linux", "x86_64")
        except FileNotFoundError:
            pytest.skip("No linux runner for x86_64")

        blob = get_blob("ul_exec", "linux", "x86_64")
        # Valid ELF magic but truncated
        config = _build_ul_exec_config(b"\x7fELF" + b"\x00" * 12, argv=["trunc"])

        result = run_blob(blob, config=config, timeout=10.0)
        assert result.exit_code != 0
