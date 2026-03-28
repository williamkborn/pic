"""Module extension for locating the host qemu-arm-static binary.

QEMU user-mode static is a system prerequisite (like a kernel). This
extension wraps the host binary into a Bazel-visible label so tests
can declare it as a dependency.
"""

def _qemu_repo_impl(ctx):
    qemu = ctx.which("qemu-arm-static")
    if not qemu:
        fail(
            "qemu-arm-static not found on PATH. " +
            "Install it: apt install qemu-user-static",
        )

    ctx.symlink(qemu, "qemu-arm-static")
    ctx.file("BUILD.bazel", """\
package(default_visibility = ["//visibility:public"])

filegroup(
    name = "qemu",
    srcs = ["qemu-arm-static"],
)
""")

qemu_arm_repo = repository_rule(
    implementation = _qemu_repo_impl,
    local = True,
)

def _qemu_impl(module_ctx):
    qemu_arm_repo(name = "qemu_arm_static")

qemu = module_extension(
    implementation = _qemu_impl,
)
