# Running Blobs

The `picblobs` CLI operates on blobs staged in the package. It has no
knowledge of the build system.

```bash
# Run hello on x86_64 (native -- no QEMU)
picblobs run hello

# Run hello on a cross architecture (via QEMU)
picblobs run hello linux:aarch64

# Run hello_windows through the mock TEB/PEB runner
picblobs run hello_windows windows:x86_64

# Run a .so file directly (development)
picblobs run --so bazel-bin/src/payload/hello.so linux:mipsel32

# Verify all staged blobs on all architectures
picblobs verify

# Verify a specific OS
picblobs verify --os windows

# List all blobs in the package
picblobs list

# Show blob metadata
picblobs info hello linux:x86_64
picblobs info hello_windows windows:i686
```
