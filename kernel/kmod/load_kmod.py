#!/usr/bin/env python3
"""
Kernel module PIC blob loader — companion script for pic_kmod.ko

Extracts a PIC blob from the picblobs package, prepares it for kernel
context, builds and loads the kernel module.

Usage:
  # Build the kernel module
  sudo python3 mbed/kmod_loader/load_kmod.py build

  # Extract a blob and load it into kernel via the module
  sudo python3 mbed/kmod_loader/load_kmod.py load --blob-type hello

  # Load and execute in ring 0 (DANGEROUS — blob must be kernel-safe)
  sudo python3 mbed/kmod_loader/load_kmod.py load --blob-type hello --exec

  # Load with rootkit hiding demo
  sudo python3 mbed/kmod_loader/load_kmod.py load --blob-type hello --hide

  # Unload the module
  sudo python3 mbed/kmod_loader/load_kmod.py unload

  # Show module status
  sudo python3 mbed/kmod_loader/load_kmod.py status
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KMOD_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))


def cmd_build(args):
    """Build the kernel module."""
    print(f"[*] Building pic_kmod.ko...")
    print(f"[*] Module source: {KMOD_DIR / 'pic_kmod.c'}")
    print(f"[*] Kernel build dir: /lib/modules/{os.uname().release}/build\n")

    ret = subprocess.run(["make", "-C", str(KMOD_DIR)],
                         capture_output=not args.verbose)
    if ret.returncode != 0:
        print(f"[!] Build failed")
        if not args.verbose:
            print(ret.stderr.decode())
        return 1

    ko_path = KMOD_DIR / "pic_kmod.ko"
    if ko_path.exists():
        size = ko_path.stat().st_size
        print(f"[+] Built: {ko_path} ({size} bytes)")
    else:
        print(f"[!] pic_kmod.ko not found after build")
        return 1

    return 0


def cmd_load(args):
    """Extract blob and load kernel module."""
    # Build first if needed
    ko_path = KMOD_DIR / "pic_kmod.ko"
    if not ko_path.exists():
        print(f"[*] pic_kmod.ko not found, building...")
        ret = subprocess.run(["make", "-C", str(KMOD_DIR)], capture_output=True)
        if ret.returncode != 0:
            print(f"[!] Build failed: {ret.stderr.decode()}")
            return 1

    # Extract blob to temp file
    blob_path = ""
    if args.blob_type:
        from picblobs import get_blob
        from picblobs._extractor import extract

        if args.so:
            blob = extract(args.so)
        else:
            blob = get_blob(args.blob_type, args.blob_os, args.blob_arch)

        print(f"[*] Blob: {blob.blob_type}/{blob.target_os}/{blob.target_arch}")
        print(f"[*] Code size: {len(blob.code)} bytes")
        print(f"[*] SHA-256: {blob.sha256[:16]}...")

        # Write flat blob to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".bin", delete=False,
                                         prefix="kblob_")
        tmp.write(blob.code)
        tmp.close()
        blob_path = tmp.name
        print(f"[*] Blob written to: {blob_path}")

    # Unload existing module if loaded
    ret = subprocess.run(["lsmod"], capture_output=True, text=True)
    if "pic_kmod" in ret.stdout:
        print(f"[*] Unloading existing pic_kmod...")
        subprocess.run(["rmmod", "pic_kmod"], capture_output=True)

    # Build insmod command
    insmod_args = ["insmod", str(ko_path)]
    if blob_path:
        insmod_args.append(f"blob_path={blob_path}")
    if args.exec:
        insmod_args.append("exec_blob=1")
    if args.hide:
        insmod_args.append("hide=1")

    print(f"\n[*] ══════ LOADING KERNEL MODULE ══════")
    print(f"[*] Command: {' '.join(insmod_args)}")

    if args.exec:
        print(f"\n[!] WARNING: exec_blob=1 — the blob will execute in ring 0")
        print(f"[!] Userspace blobs (hello, ul_exec) use syscall instructions")
        print(f"[!] which will NOT work in kernel context. Only load blobs")
        print(f"[!] specifically designed for kernel execution.\n")

    print()
    ret = subprocess.run(insmod_args, capture_output=True, text=True)
    if ret.returncode != 0:
        print(f"[!] insmod failed: {ret.stderr.strip()}")
        return 1

    print(f"[+] Module loaded successfully")

    # Show dmesg output
    print(f"\n[*] ── dmesg output ──")
    dmesg = subprocess.run(["dmesg"], capture_output=True, text=True)
    lines = dmesg.stdout.strip().split("\n")
    for line in lines:
        if "pic_kmod" in line:
            print(f"  {line}")

    # Show module info
    print()
    if not args.hide:
        ret = subprocess.run(["lsmod"], capture_output=True, text=True)
        for line in ret.stdout.splitlines():
            if "pic_kmod" in line:
                print(f"[*] lsmod: {line}")
    else:
        print(f"[*] Module hidden — lsmod will NOT show it")
        print(f"[*] Use ebpf_kernel_mem.py modules --check-hidden to find it")

    # Cleanup temp file (unless exec, keep for debugging)
    if blob_path and not args.exec:
        os.unlink(blob_path)

    return 0


def cmd_unload(args):
    """Unload the kernel module."""
    print(f"[*] Unloading pic_kmod...")
    ret = subprocess.run(["rmmod", "pic_kmod"], capture_output=True, text=True)
    if ret.returncode != 0:
        if "not found" in ret.stderr or "not currently loaded" in ret.stderr:
            print(f"[*] Module not loaded (may be hidden)")
        else:
            print(f"[!] rmmod failed: {ret.stderr.strip()}")
            return 1
    else:
        print(f"[+] Module unloaded")

    # Show dmesg
    dmesg = subprocess.run(["dmesg"], capture_output=True, text=True)
    for line in dmesg.stdout.strip().split("\n")[-5:]:
        if "pic_kmod" in line:
            print(f"  {line}")

    return 0


def cmd_status(args):
    """Show module status and kernel context info."""
    print(f"\n[*] ══════ KERNEL MODULE STATUS ══════\n")

    # Check if loaded
    ret = subprocess.run(["lsmod"], capture_output=True, text=True)
    loaded = "pic_kmod" in ret.stdout
    print(f"  Module loaded (visible):  {'yes' if loaded else 'no'}")

    if loaded:
        for line in ret.stdout.splitlines():
            if "pic_kmod" in line:
                parts = line.split()
                print(f"  Module size:              {parts[1]} bytes")
                print(f"  Used by:                  {parts[2]} modules")

    # Check dmesg for module info
    dmesg = subprocess.run(["dmesg"], capture_output=True, text=True)
    print(f"\n  Recent dmesg entries:")
    for line in dmesg.stdout.strip().split("\n"):
        if "pic_kmod" in line:
            print(f"    {line}")

    # Check /proc/modules
    try:
        with open("/proc/modules") as f:
            modules_text = f.read()
        if "pic_kmod" in modules_text:
            print(f"\n  /proc/modules:            VISIBLE")
        else:
            print(f"\n  /proc/modules:            NOT VISIBLE (hidden?)")
    except PermissionError:
        pass

    # Check sysfs
    sysfs_path = Path("/sys/module/pic_kmod")
    print(f"  /sys/module/pic_kmod:     "
          f"{'exists' if sysfs_path.exists() else 'not found'}")

    # Kernel info
    print(f"\n  Kernel:                   {os.uname().release}")
    print(f"  Architecture:             {os.uname().machine}")

    # Check for kernel headers (needed for build)
    kdir = Path(f"/lib/modules/{os.uname().release}/build")
    print(f"  Kernel headers:           "
          f"{'installed' if kdir.exists() else 'MISSING'}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Kernel Module PIC Blob Loader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  build   — Compile pic_kmod.ko
  load    — Extract blob + insmod the module
  unload  — rmmod the module
  status  — Show module status

Examples:
  sudo python3 mbed/kmod_loader/load_kmod.py build
  sudo python3 mbed/kmod_loader/load_kmod.py load --blob-type hello
  sudo python3 mbed/kmod_loader/load_kmod.py load --hide
  sudo python3 mbed/kmod_loader/load_kmod.py status
  sudo python3 mbed/kmod_loader/load_kmod.py unload
        """)

    subs = parser.add_subparsers(dest="command", required=True)

    p_build = subs.add_parser("build", help="Build pic_kmod.ko")
    p_build.add_argument("-v", "--verbose", action="store_true")

    p_load = subs.add_parser("load", help="Load module with blob")
    p_load.add_argument("--blob-type", default="")
    p_load.add_argument("--blob-os", default="linux")
    p_load.add_argument("--blob-arch", default="x86_64")
    p_load.add_argument("--so", default="")
    p_load.add_argument("--exec", action="store_true",
                        help="Execute blob in ring 0 (kernel-safe blobs only)")
    p_load.add_argument("--hide", action="store_true",
                        help="Hide module from /proc/modules")

    p_unload = subs.add_parser("unload", help="Unload module")
    p_status = subs.add_parser("status", help="Show module status")

    args = parser.parse_args()

    if os.geteuid() != 0 and args.command != "status":
        print("[!] Requires root for kernel module operations")
        return 1

    return {"build": cmd_build, "load": cmd_load,
            "unload": cmd_unload, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
