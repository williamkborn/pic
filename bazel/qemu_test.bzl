"""Bazel rules for running blob tests under QEMU user-static.

Implements the test execution model from MOD-006:
  - Linux runners:   real syscalls via QEMU emulation
  - FreeBSD runners: shim-redirected syscalls for verification
  - Windows runners: mock TEB/PEB environment

Usage:
  qemu_blob_test(
      name = "alloc_jump_x86_64_linux_test",
      runner = "//tests/runners/linux:runner_x86_64",
      blob = "//src/blob:alloc_jump_linux_x86_64",
      arch = "x86_64",
      runner_type = "linux",
  )
"""

# QEMU binary names per architecture.
_QEMU_BINARIES = {
    "x86_64": "qemu-x86_64-static",
    "i686": "qemu-i386-static",
    "aarch64": "qemu-aarch64-static",
    "armv5_arm": "qemu-arm-static",
    "armv5_thumb": "qemu-arm-static",
    "mipsel32": "qemu-mipsel-static",
    "mipsbe32": "qemu-mips-static",
}

def _qemu_blob_test_impl(ctx):
    """Test rule that runs a blob under a test runner via QEMU."""
    runner = ctx.executable.runner
    blob_files = ctx.attr.blob.files.to_list()
    arch = ctx.attr.arch
    runner_type = ctx.attr.runner_type
    qemu = _QEMU_BINARIES.get(arch, "qemu-{}-static".format(arch))

    # Find the .bin file from the blob target.
    bin_file = None
    for f in blob_files:
        if f.extension == "bin":
            bin_file = f
            break

    if not bin_file:
        fail("No .bin file found in blob target {}".format(ctx.attr.blob.label))

    # Generate the test script.
    script = ctx.actions.declare_file(ctx.attr.name + "_qemu_test.sh")

    # For native x86_64 on x86_64 host, run directly without QEMU.
    if arch == "x86_64":
        run_cmd = "./{runner} ./{blob}".format(
            runner = runner.short_path,
            blob = bin_file.short_path,
        )
    else:
        run_cmd = "{qemu} ./{runner} ./{blob}".format(
            qemu = qemu,
            runner = runner.short_path,
            blob = bin_file.short_path,
        )

    ctx.actions.write(
        output = script,
        content = """\
#!/bin/bash
set -euo pipefail
# QEMU blob test: {label}
# Runner type: {runner_type}, Arch: {arch}

{run_cmd}
""".format(
            label = ctx.label,
            runner_type = runner_type,
            arch = arch,
            run_cmd = run_cmd,
        ),
        is_executable = True,
    )

    runfiles = ctx.runfiles(files = [runner, bin_file])

    return [DefaultInfo(
        executable = script,
        runfiles = runfiles,
    )]

qemu_blob_test = rule(
    implementation = _qemu_blob_test_impl,
    test = True,
    attrs = {
        "runner": attr.label(
            mandatory = True,
            executable = True,
            cfg = "target",
            doc = "Test runner binary (compiled for the target architecture).",
        ),
        "blob": attr.label(
            mandatory = True,
            doc = "Blob target (blob_extract output).",
        ),
        "arch": attr.string(
            mandatory = True,
            doc = "Target architecture for QEMU binary selection.",
        ),
        "runner_type": attr.string(
            mandatory = True,
            values = ["linux", "freebsd", "windows"],
            doc = "Type of test runner (determines verification strategy).",
        ),
    },
    doc = "Runs a blob under a test runner via QEMU user-static.",
)

def qemu_blob_test_suite(
        name,
        runner,
        blobs,
        arch,
        runner_type,
        **kwargs):
    """Creates a qemu_blob_test for each blob in the list.

    Args:
        name: Suite name prefix.
        runner: Test runner label.
        blobs: Dict of {blob_name: blob_label}.
        arch: Target architecture.
        runner_type: Runner type (linux/freebsd/windows).
        **kwargs: Passed to each test.
    """
    tests = []
    for blob_name, blob_label in blobs.items():
        test_name = "{}_{}".format(name, blob_name)
        qemu_blob_test(
            name = test_name,
            runner = runner,
            blob = blob_label,
            arch = arch,
            runner_type = runner_type,
            **kwargs
        )
        tests.append(test_name)

    native.test_suite(
        name = name,
        tests = [":" + t for t in tests],
    )
