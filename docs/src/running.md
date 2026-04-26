# Running Blobs

The `picblobs-cli` CLI operates on blobs staged in the package. It has
no knowledge of the build system.

```bash
# Run hello on x86_64 (native -- no QEMU)
picblobs-cli run hello linux:x86_64

# Run hello on a cross architecture (via QEMU)
picblobs-cli run hello linux:aarch64

# Run hello_windows through the mock TEB/PEB runner
picblobs-cli run hello_windows windows:x86_64

# Verify all staged blobs on all architectures
picblobs-cli verify

# Verify a specific OS
picblobs-cli verify --os windows

# List all blobs in the package
picblobs-cli list

# Show blob metadata
picblobs-cli info hello linux:x86_64
picblobs-cli info hello_windows windows:i686
```
