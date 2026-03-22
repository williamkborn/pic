"""Helper macro for registering Bootlin CC toolchains."""

load("@rules_cc//cc:defs.bzl", "cc_toolchain")
load(":cc_toolchain_config.bzl", "picblobs_cc_toolchain_config")

def bootlin_cc_toolchain(name, triple, target_cpu, repo, extra_cflags = [], compatible_with = []):
    """Registers a Bootlin cc_toolchain, its config, and the toolchain() binding.

    Args:
        name: Toolchain name (e.g., "bootlin_x86_64").
        triple: GCC target triple (e.g., "x86_64-buildroot-linux-gnu").
        target_cpu: Bazel CPU identifier (e.g., "x86_64").
        repo: External repository name for the Bootlin archive.
        extra_cflags: Additional architecture-specific compiler flags.
        compatible_with: Constraint values for toolchain resolution.
    """
    config_name = "{}_config".format(name)

    picblobs_cc_toolchain_config(
        name = config_name,
        triple = triple,
        toolchain_root = "external/{}".format(repo),
        target_cpu = target_cpu,
        extra_cflags = extra_cflags,
    )

    cc_toolchain(
        name = "{}_cc".format(name),
        toolchain_config = ":{}".format(config_name),
        all_files = "@{}//:all_files".format(repo),
        compiler_files = "@{}//:compiler_files".format(repo),
        linker_files = "@{}//:linker_files".format(repo),
        ar_files = "@{}//:ar_files".format(repo),
        objcopy_files = "@{}//:objcopy_files".format(repo),
        strip_files = "@{}//:strip_files".format(repo),
        dwp_files = "@{}//:all_files".format(repo),
    )

    native.toolchain(
        name = name,
        toolchain = ":{}_cc".format(name),
        toolchain_type = "@rules_cc//cc:toolchain_type",
        target_compatible_with = compatible_with,
    )
