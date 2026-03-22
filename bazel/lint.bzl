"""C linting and static analysis integration for Bazel.

Provides two mechanisms:
  1. clang_tidy_aspect  — runs clang-tidy on cc_library/cc_binary targets
  2. cppcheck_test      — runs cppcheck as a Bazel test

Usage:
  # Run clang-tidy on all C targets:
  bazel build --config=lint //src/...

  # Run cppcheck as a test:
  bazel test //src:cppcheck
"""

load("@rules_cc//cc:action_names.bzl", "ACTION_NAMES")
load("@rules_cc//cc/common:cc_info.bzl", "CcInfo")

# ============================================================
# clang-tidy aspect
# ============================================================

def _clang_tidy_aspect_impl(target, ctx):
    """Aspect that runs clang-tidy on C compilation actions."""

    # Only apply to targets that provide CcInfo.
    if not CcInfo in target:
        return []

    cc_info = target[CcInfo]
    compilation_context = cc_info.compilation_context

    # Collect source files from the rule's srcs.
    srcs = []
    if hasattr(ctx.rule.attr, "srcs"):
        for src in ctx.rule.attr.srcs:
            for f in src.files.to_list():
                if f.extension in ("c", "h", "cc", "cpp"):
                    srcs.append(f)

    if not srcs:
        return [OutputGroupInfo(lint_results = depset())]

    outputs = []
    for src in srcs:
        if src.extension == "h":
            continue

        lint_output = ctx.actions.declare_file(
            "{}.clang-tidy.txt".format(src.short_path),
        )
        outputs.append(lint_output)

        # Build include flags from the compilation context.
        include_flags = []
        for inc in compilation_context.includes.to_list():
            include_flags.extend(["-I", inc])
        for inc in compilation_context.system_includes.to_list():
            include_flags.extend(["-isystem", inc])
        for inc in compilation_context.quote_includes.to_list():
            include_flags.extend(["-iquote", inc])

        # Collect all header files for inputs.
        header_inputs = compilation_context.headers.to_list()

        args = ctx.actions.args()
        args.add(src)
        args.add("--quiet")
        args.add("--warnings-as-errors=*")
        args.add_all(include_flags)
        args.add("--")
        args.add("-ffreestanding")
        args.add("-fno-builtin")

        ctx.actions.run_shell(
            outputs = [lint_output],
            inputs = [src] + header_inputs,
            command = """
                if command -v clang-tidy >/dev/null 2>&1; then
                    clang-tidy "$@" > {out} 2>&1 || true
                else
                    echo "clang-tidy not found, skipping" > {out}
                fi
            """.format(out = lint_output.path),
            arguments = [args],
            mnemonic = "ClangTidy",
            progress_message = "Running clang-tidy on %{label}: {}".format(src.short_path),
        )

    return [OutputGroupInfo(lint_results = depset(outputs))]

clang_tidy_aspect = aspect(
    implementation = _clang_tidy_aspect_impl,
    attr_aspects = ["deps"],
    doc = "Runs clang-tidy on C source files.",
)

# ============================================================
# cppcheck test rule
# ============================================================

def _cppcheck_test_impl(ctx):
    """Test rule that runs cppcheck on a set of source files."""
    srcs = []
    for src in ctx.attr.srcs:
        srcs.extend(src.files.to_list())

    include_dirs = ctx.attr.include_dirs

    script = ctx.actions.declare_file(ctx.attr.name + "_cppcheck.sh")

    include_flags = " ".join(["-I {}".format(d) for d in include_dirs])
    src_paths = " ".join([f.short_path for f in srcs])

    ctx.actions.write(
        output = script,
        content = """\
#!/bin/bash
set -euo pipefail

if ! command -v cppcheck >/dev/null 2>&1; then
    echo "cppcheck not found, skipping"
    exit 0
fi

exec cppcheck \\
    --error-exitcode=1 \\
    --enable=warning,performance,portability \\
    --suppress=missingIncludeSystem \\
    --inline-suppr \\
    --language=c \\
    --std=c11 \\
    {include_flags} \\
    {srcs}
""".format(include_flags = include_flags, srcs = src_paths),
        is_executable = True,
    )

    runfiles = ctx.runfiles(files = srcs)

    return [DefaultInfo(
        executable = script,
        runfiles = runfiles,
    )]

cppcheck_test = rule(
    implementation = _cppcheck_test_impl,
    test = True,
    attrs = {
        "srcs": attr.label_list(
            mandatory = True,
            allow_files = [".c", ".h"],
            doc = "C source and header files to check.",
        ),
        "include_dirs": attr.string_list(
            default = ["src/include"],
            doc = "Include directories for cppcheck.",
        ),
    },
    doc = "Runs cppcheck as a Bazel test.",
)
