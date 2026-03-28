"""C linting and formatting checks for Bazel.

Provides:
  1. clang_tidy_aspect   — runs clang-tidy on cc_library/cc_binary targets
  2. clang_format_test   — verifies C files are formatted per .clang-format
  3. cppcheck_test       — runs cppcheck as a Bazel test

Usage:
  # Run clang-tidy on all C targets:
  bazel build --config=lint //src/... //tests/...

  # Check formatting:
  bazel test //src:format_check

  # Run cppcheck:
  bazel test //src:cppcheck
"""

load("@rules_cc//cc/common:cc_info.bzl", "CcInfo")

# ============================================================
# clang-tidy aspect
# ============================================================

def _clang_tidy_aspect_impl(target, ctx):
    """Aspect that runs clang-tidy on C source files.

    Fails the build if clang-tidy reports any warnings or errors.
    """
    if not CcInfo in target:
        return []

    cc_info = target[CcInfo]
    compilation_context = cc_info.compilation_context

    srcs = []
    if hasattr(ctx.rule.attr, "srcs"):
        for src in ctx.rule.attr.srcs:
            for f in src.files.to_list():
                if f.extension == "c":
                    srcs.append(f)

    if not srcs:
        return [OutputGroupInfo(lint_results = depset())]

    outputs = []
    for src in srcs:
        lint_output = ctx.actions.declare_file(
            "{}.clang-tidy.txt".format(src.short_path),
        )
        outputs.append(lint_output)

        include_flags = []
        for inc in compilation_context.includes.to_list():
            include_flags.extend(["-I", inc])
        for inc in compilation_context.system_includes.to_list():
            include_flags.extend(["-isystem", inc])
        for inc in compilation_context.quote_includes.to_list():
            include_flags.extend(["-iquote", inc])

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
                if ! command -v clang-tidy >/dev/null 2>&1; then
                    if [ -n "${{PICBLOBS_REQUIRE_LINT_TOOLS:-}}" ]; then
                        echo "ERROR: clang-tidy not found but PICBLOBS_REQUIRE_LINT_TOOLS is set" >&2
                        exit 1
                    fi
                    echo "SKIP: clang-tidy not found" > {out}
                    exit 0
                fi
                clang-tidy "$@" > {out} 2>&1
                status=$?
                if [ $status -ne 0 ]; then
                    cat {out} >&2
                    exit $status
                fi
            """.format(out = lint_output.path),
            arguments = [args],
            mnemonic = "ClangTidy",
            progress_message = "clang-tidy %{{label}}: {}".format(src.short_path),
        )

    return [OutputGroupInfo(lint_results = depset(outputs))]

clang_tidy_aspect = aspect(
    implementation = _clang_tidy_aspect_impl,
    attr_aspects = ["deps"],
    doc = "Runs clang-tidy on C source files. Fails on warnings.",
)

# ============================================================
# clang-format check test
# ============================================================

def _clang_format_test_impl(ctx):
    """Test rule that verifies C files are formatted per .clang-format."""
    srcs = []
    for src in ctx.attr.srcs:
        srcs.extend(src.files.to_list())

    config = ctx.file.config

    script = ctx.actions.declare_file(ctx.attr.name + "_format_check.sh")

    src_paths = " ".join([f.short_path for f in srcs])

    ctx.actions.write(
        output = script,
        content = """\
#!/bin/bash
set -euo pipefail

if ! command -v clang-format >/dev/null 2>&1; then
    if [ -n "${{PICBLOBS_REQUIRE_LINT_TOOLS:-}}" ]; then
        echo "ERROR: clang-format not found but PICBLOBS_REQUIRE_LINT_TOOLS is set" >&2
        exit 1
    fi
    echo "SKIP: clang-format not found"
    exit 0
fi

failed=0
for f in {srcs}; do
    if ! clang-format --dry-run --Werror --style=file:{config} "$f" 2>/dev/null; then
        echo "FAIL: $f"
        failed=1
    fi
done

if [ $failed -ne 0 ]; then
    echo ""
    echo "Run: python tools/fmt.py"
    exit 1
fi

echo "{count} files formatted correctly"
""".format(
            srcs = src_paths,
            config = config.short_path,
            count = len(srcs),
        ),
        is_executable = True,
    )

    runfiles = ctx.runfiles(files = srcs + [config])

    return [DefaultInfo(
        executable = script,
        runfiles = runfiles,
    )]

clang_format_test = rule(
    implementation = _clang_format_test_impl,
    test = True,
    attrs = {
        "srcs": attr.label_list(
            mandatory = True,
            allow_files = [".c", ".h"],
            doc = "C source and header files to check.",
        ),
        "config": attr.label(
            mandatory = True,
            allow_single_file = True,
            doc = "The .clang-format config file.",
        ),
    },
    doc = "Verifies C files are formatted per .clang-format.",
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
    if [ -n "${{PICBLOBS_REQUIRE_LINT_TOOLS:-}}" ]; then
        echo "ERROR: cppcheck not found but PICBLOBS_REQUIRE_LINT_TOOLS is set" >&2
        exit 1
    fi
    echo "SKIP: cppcheck not found"
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
