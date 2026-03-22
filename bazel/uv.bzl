"""Bazel rules for building the Python wheel via uv.

Wraps uv build so that wheel packaging participates in the Bazel
build graph. The rule stages .so blob files into the Python package
tree and invokes uv to build the wheel.

This implements Stage 7 of MOD-002 (build pipeline).
"""

def _uv_wheel_impl(ctx):
    """Builds a Python wheel using uv."""
    wheel_output = ctx.actions.declare_file(ctx.attr.wheel_name)
    package_dir = ctx.file.package_dir

    # Collect all blob .so files.
    blob_files = []
    for target in ctx.attr.blobs:
        blob_files.extend(target.files.to_list())

    # Collect generated Python sources.
    gen_files = []
    for target in ctx.attr.generated_srcs:
        gen_files.extend(target.files.to_list())

    # Collect Python package sources.
    src_files = []
    for target in ctx.attr.srcs:
        src_files.extend(target.files.to_list())

    all_inputs = blob_files + gen_files + src_files + [package_dir]

    # Stage blob .so files into _blobs/{os}/{arch}/ directory.
    # The blob file's short_path encodes the target structure.
    staging_lines = []
    for f in blob_files:
        staging_lines.append(
            "mkdir -p \"$STAGING_DIR/picblobs/_blobs/$(dirname " + f.short_path + ")\" && " +
            "cp " + f.path + " \"$STAGING_DIR/picblobs/_blobs/" + f.short_path + "\"",
        )

    # Stage generated Python files.
    for f in gen_files:
        staging_lines.append(
            "mkdir -p \"$STAGING_DIR/picblobs/_generated\" && " +
            "cp " + f.path + " \"$STAGING_DIR/picblobs/_generated/" + f.basename + "\"",
        )

    staging_block = "\n".join(staging_lines)

    script_content = "\n".join([
        "#!/bin/bash",
        "set -euo pipefail",
        "",
        "STAGING_DIR=$(mktemp -d)",
        "trap 'rm -rf \"$STAGING_DIR\"' EXIT",
        "",
        "# Copy the Python package source tree.",
        "cp -r " + package_dir.path + "/* \"$STAGING_DIR/\"",
        "",
        staging_block,
        "",
        "# Build the wheel.",
        "cd \"$STAGING_DIR\"",
        "uv build --wheel --out-dir \"$OLDPWD/$(dirname " + wheel_output.path + ")\"",
        "",
        "# Rename to expected output name.",
        "BUILT_WHEEL=$(ls \"$OLDPWD/$(dirname " + wheel_output.path + ")\"/*.whl | head -1)",
        "mv \"$BUILT_WHEEL\" \"$OLDPWD/" + wheel_output.path + "\"",
    ])

    script = ctx.actions.declare_file(ctx.attr.name + "_build_wheel.sh")
    ctx.actions.write(
        output = script,
        content = script_content,
        is_executable = True,
    )

    ctx.actions.run(
        executable = script,
        inputs = all_inputs,
        outputs = [wheel_output],
        tools = [],
        mnemonic = "UvBuild",
        progress_message = "Building Python wheel via uv",
        use_default_shell_env = True,
    )

    return [DefaultInfo(files = depset([wheel_output]))]

uv_wheel = rule(
    implementation = _uv_wheel_impl,
    attrs = {
        "package_dir": attr.label(
            mandatory = True,
            allow_single_file = True,
        ),
        "blobs": attr.label_list(default = []),
        "generated_srcs": attr.label_list(default = []),
        "srcs": attr.label_list(
            default = [],
            allow_files = [".py"],
        ),
        "wheel_name": attr.string(
            default = "picblobs-0.1.0-py3-none-any.whl",
        ),
    },
)
