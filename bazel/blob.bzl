"""Custom Bazel rules for building PIC blobs as shared objects.

The blob pipeline is:
  1. cc_library      → object files (.a archive)
  2. genrule (gcc)   → .so (shared object with custom linker script)
  3. blob_stage      → copies .so into python/picblobs/_blobs/{os}/{arch}/

We use a genrule instead of cc_binary for linking because cc_binary
injects -Wl,-S (strip) which removes the .text and .rodata sections
we need pyelftools to read at runtime.
"""

load("@rules_cc//cc:defs.bzl", "cc_library")

# All target platforms we build blobs for.
BLOB_TARGETS = {
    "linux:x86_64": "//platforms:linux_x86_64",
    "linux:i686": "//platforms:linux_i686",
    "linux:aarch64": "//platforms:linux_aarch64",
    "linux:armv5_arm": "//platforms:linux_armv5_arm",
    "linux:mipsel32": "//platforms:linux_mipsel32",
    "linux:mipsbe32": "//platforms:linux_mipsbe32",
}

def pic_blob(
        name,
        srcs,
        deps = [],
        hdrs = [],
        linker_script = None,
        copts = [],
        linkopts = [],
        **kwargs):
    """Compile and link a PIC blob as a shared object.

    Creates:
      - {name}_obj : cc_library with the blob source
      - {name}     : genrule that links the .so

    Args:
        name: Blob type name (e.g., "hello", "alloc_jump").
        srcs: C source files.
        deps: cc_library dependencies.
        hdrs: Header files.
        linker_script: Label for the custom linker script.
        copts: Additional C compiler flags.
        linkopts: Additional linker flags.
        **kwargs: Passed through to generated targets.
    """
    lib_name = name + "_obj"

    cc_library(
        name = lib_name,
        srcs = srcs,
        hdrs = hdrs,
        copts = copts,
        deps = deps,
        **kwargs
    )

    linker_script_flag = ""
    srcs_list = [":" + lib_name]
    if linker_script:
        linker_script_flag = "-T$(location {})".format(linker_script)
        srcs_list.append(linker_script)

    extra_linkopts = " ".join(linkopts)

    native.genrule(
        name = name,
        srcs = srcs_list,
        outs = [name + ".so"],
        cmd = " ".join([
            "$(CC)",
            "-nostdlib",
            "-nostartfiles",
            "-shared",
            linker_script_flag,
            "-Wl,--whole-archive",
            "$(location :{})".format(lib_name),
            "-Wl,--no-whole-archive",
            extra_linkopts,
            "-o $@",
        ]),
        toolchains = ["@rules_cc//cc:current_cc_toolchain"],
        **kwargs
    )

def blob_collection(name, blobs, **kwargs):
    """Collects multiple blob .so targets into a single filegroup."""
    native.filegroup(
        name = name,
        srcs = blobs,
        **kwargs
    )
