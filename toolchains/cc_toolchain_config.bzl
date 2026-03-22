"""CC toolchain configuration for freestanding PIC blob compilation.

Generates cc_toolchain_config targets for each Bootlin cross-compiler.
All toolchains share the same freestanding compilation model:
  -ffreestanding -nostdlib -nostartfiles -fno-builtin
  -fPIC -ffunction-sections -fdata-sections -Os -Wall -Werror
"""

load("@rules_cc//cc:action_names.bzl", "ACTION_NAMES")
load(
    "@rules_cc//cc:cc_toolchain_config_lib.bzl",
    "feature",
    "flag_group",
    "flag_set",
    "tool_path",
)
load("@rules_cc//cc/common:cc_common.bzl", "cc_common")
load(
    "@rules_cc//cc/toolchains:cc_toolchain_config_info.bzl",
    "CcToolchainConfigInfo",
)

_ALL_COMPILE_ACTIONS = [
    ACTION_NAMES.c_compile,
    ACTION_NAMES.cpp_compile,
    ACTION_NAMES.assemble,
    ACTION_NAMES.preprocess_assemble,
]

_ALL_LINK_ACTIONS = [
    ACTION_NAMES.cpp_link_executable,
    ACTION_NAMES.cpp_link_dynamic_library,
    ACTION_NAMES.cpp_link_nodeps_dynamic_library,
]

def _impl(ctx):
    triple = ctx.attr.triple
    toolchain_root = ctx.attr.toolchain_root
    extra_cflags = ctx.attr.extra_cflags

    tool_paths = [
        tool_path(name = "gcc", path = "{}/bin/{}-gcc".format(toolchain_root, triple)),
        tool_path(name = "g++", path = "{}/bin/{}-g++".format(toolchain_root, triple)),
        tool_path(name = "ld", path = "{}/bin/{}-ld".format(toolchain_root, triple)),
        tool_path(name = "ar", path = "{}/bin/{}-ar".format(toolchain_root, triple)),
        tool_path(name = "nm", path = "{}/bin/{}-nm".format(toolchain_root, triple)),
        tool_path(name = "objcopy", path = "{}/bin/{}-objcopy".format(toolchain_root, triple)),
        tool_path(name = "objdump", path = "{}/bin/{}-objdump".format(toolchain_root, triple)),
        tool_path(name = "strip", path = "{}/bin/{}-strip".format(toolchain_root, triple)),
        tool_path(name = "as", path = "{}/bin/{}-as".format(toolchain_root, triple)),
        tool_path(name = "cpp", path = "{}/bin/{}-cpp".format(toolchain_root, triple)),
        tool_path(name = "gcov", path = "/usr/bin/false"),
        tool_path(name = "dwp", path = "/usr/bin/false"),
    ]

    # Freestanding compilation flags — shared by all blob targets.
    freestanding_feature = feature(
        name = "freestanding",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = _ALL_COMPILE_ACTIONS,
                flag_groups = [
                    flag_group(
                        flags = [
                            "-ffreestanding",
                            "-fno-builtin",
                            "-fPIC",
                            "-ffunction-sections",
                            "-fdata-sections",
                            "-Os",
                            "-Wall",
                            "-Werror",
                        ],
                    ),
                ],
            ),
            flag_set(
                actions = _ALL_LINK_ACTIONS,
                flag_groups = [
                    flag_group(
                        flags = [
                            "-nostdlib",
                            "-nostartfiles",
                            "-Wl,--gc-sections",
                        ],
                    ),
                ],
            ),
        ],
    )

    # Architecture-specific flags.
    arch_flags_feature = feature(
        name = "arch_flags",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = _ALL_COMPILE_ACTIONS,
                flag_groups = [
                    flag_group(flags = extra_cflags),
                ] if extra_cflags else [],
            ),
        ],
    ) if extra_cflags else None

    # Include paths for our own headers.
    includes_feature = feature(
        name = "pic_includes",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = _ALL_COMPILE_ACTIONS,
                flag_groups = [
                    flag_group(
                        flags = ["-isystem", "src/include"],
                    ),
                ],
            ),
        ],
    )

    features = [
        freestanding_feature,
        includes_feature,
    ]
    if arch_flags_feature:
        features.append(arch_flags_feature)

    return cc_common.create_cc_toolchain_config_info(
        ctx = ctx,
        toolchain_identifier = "bootlin_{}".format(ctx.attr.name),
        host_system_name = "x86_64-linux-gnu",
        target_system_name = triple,
        target_cpu = ctx.attr.target_cpu,
        target_libc = "glibc",
        compiler = "gcc",
        abi_version = "gcc",
        abi_libc_version = "glibc",
        tool_paths = tool_paths,
        features = features,
    )

picblobs_cc_toolchain_config = rule(
    implementation = _impl,
    attrs = {
        "triple": attr.string(mandatory = True),
        "toolchain_root": attr.string(mandatory = True),
        "target_cpu": attr.string(mandatory = True),
        "extra_cflags": attr.string_list(default = []),
    },
    provides = [CcToolchainConfigInfo],
)
