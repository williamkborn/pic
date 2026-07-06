"""Module extension for a hermetic qemu-arm user-mode interpreter.

The Bazel E2E tests execute ARM Linux binaries, so QEMU must be an ordinary
declared input rather than something discovered on the submitting host or
remote worker. This extension downloads a pinned static qemu-arm binary and
exposes it as ``@qemu_arm_static//:qemu``.
"""

_QEMU_ARM_URL = (
    "https://github.com/multiarch/qemu-user-static/releases/download/" +
    "v7.2.0-1/qemu-arm-static.tar.gz"
)
_QEMU_ARM_SHA256 = "5c90e585443b6656fae712f4bc0aae317519fe12412fb97a9486b566766d8058"

def _qemu_repo_impl(ctx):
    ctx.download_and_extract(
        url = [ctx.attr.url],
        sha256 = ctx.attr.sha256,
    )
    ctx.file("BUILD.bazel", """\
package(default_visibility = ["//visibility:public"])

filegroup(
    name = "qemu",
    srcs = ["{binary}"],
)
""".format(binary = ctx.attr.binary))

qemu_arm_repo = repository_rule(
    implementation = _qemu_repo_impl,
    attrs = {
        "binary": attr.string(default = "qemu-arm-static"),
        "sha256": attr.string(default = _QEMU_ARM_SHA256),
        "url": attr.string(default = _QEMU_ARM_URL),
    },
)

def _qemu_impl(_module_ctx):
    qemu_arm_repo(name = "qemu_arm_static")

qemu = module_extension(
    implementation = _qemu_impl,
)
