"""pytest configuration and shared fixtures for picblobs tests."""

from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path

import pytest
from ._test_env import PROJECT_ROOT, prepend_source_paths

prepend_source_paths()

from tools.registry import ARCHITECTURES, OPERATING_SYSTEMS, all_platforms
from payload_defs import all_payload_combos  # noqa: E402


BAZEL_BIN = PROJECT_ROOT / "bazel-bin"
_PACKAGE_RUNNERS = PROJECT_ROOT / "python" / "picblobs" / "_runners"
_BAZEL_RUNNER_PATHS = (
    BAZEL_BIN / "tests" / "runners" / "linux" / "runner.bin",
    BAZEL_BIN / "tests" / "runners" / "linux" / "runner",
)


def _runners_exist() -> bool:
    if any(_PACKAGE_RUNNERS.rglob("runner")):
        return True
    return any(p.exists() for p in _BAZEL_RUNNER_PATHS)


def _has_qemu() -> bool:
    return shutil.which("qemu-x86_64-static") is not None


def _can_bind_localhost() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False


def _has_any_cross_compiler() -> bool:
    try:
        from picblobs._cross_compile import find_gcc
    except ImportError:
        return False
    return any(find_gcc(arch) is not None for arch in ARCHITECTURES)


# --- Environment-based filters (set by `picblobs test --os/--arch/--type`) ---


def _env_filter(key: str) -> str:
    return os.environ.get(f"PICBLOBS_TEST_{key.upper()}", "")


# ============================================================
# Registry-driven fixtures for cross-arch parametrization
# ============================================================


def _all_arch_ids() -> list[str]:
    """Return all architecture names from the registry."""
    return list(ARCHITECTURES.keys())


def _all_platform_ids() -> list[tuple[str, str]]:
    """Return all (os, arch) pairs from the registry."""
    return all_platforms()


def _linux_arch_ids() -> list[str]:
    """Return Linux architecture names from the registry."""
    return OPERATING_SYSTEMS["linux"].architectures


@pytest.fixture(params=_all_arch_ids())
def target_arch(request: pytest.FixtureRequest) -> str:
    """Parametrized fixture: yields each registered architecture name."""
    return request.param


@pytest.fixture(params=_linux_arch_ids())
def linux_arch(request: pytest.FixtureRequest) -> str:
    """Parametrized fixture: yields each Linux architecture name."""
    return request.param


@pytest.fixture(
    params=_all_platform_ids(),
    ids=[f"{os}:{arch}" for os, arch in _all_platform_ids()],
)
def platform_pair(request: pytest.FixtureRequest) -> tuple[str, str]:
    """Parametrized fixture: yields each (os, arch) pair."""
    return request.param


# ============================================================
# Payload test fixtures (TEST-011)
# ============================================================


@pytest.fixture(
    params=all_payload_combos(),
    ids=[f"{bt}:{os}:{arch}" for bt, os, arch in all_payload_combos()],
)
def payload_combo(request: pytest.FixtureRequest) -> tuple[str, str, str]:
    """Parametrized fixture: yields (blob_type, target_os, target_arch)."""
    return request.param


# ============================================================
# Standard fixtures
# ============================================================


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def blob_dir() -> Path:
    """Path to staged .so blob files (populated by ``./buildall``)."""
    return PROJECT_ROOT / "python" / "picblobs" / "_blobs"


@pytest.fixture(scope="session")
def runner_dir() -> Path:
    """Path to built test runner binaries."""
    return BAZEL_BIN / "tests" / "runners"


@pytest.fixture(scope="session")
def runners_available() -> bool:
    """True if test runners have been built."""
    return _runners_exist()


@pytest.fixture(scope="session")
def qemu_available() -> bool:
    """True if qemu-x86_64-static is on PATH."""
    return _has_qemu()


@pytest.fixture(scope="session")
def localhost_tcp_available() -> bool:
    """True if tests may bind localhost TCP sockets in this environment."""
    return _can_bind_localhost()


@pytest.fixture(scope="session")
def cross_compile_available() -> bool:
    """True if at least one Bootlin cross-compiler is discoverable."""
    return _has_any_cross_compiler()


# ============================================================
# Markers
# ============================================================


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "requires_runners: test needs compiled C test runners"
    )
    config.addinivalue_line("markers", "requires_qemu: test needs QEMU user-static")
    config.addinivalue_line("markers", "requires_blobs: test needs built .so blobs")
    config.addinivalue_line(
        "markers",
        "requires_local_tcp: test needs permission to bind localhost TCP sockets",
    )
    config.addinivalue_line(
        "markers", "requires_cross_compile: test needs a discoverable cross-compiler"
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Auto-skip tests based on available infrastructure."""
    _apply_capability_skips(items, _capability_state())
    _apply_env_filters(items, _collection_filters())


def _capability_state() -> dict[str, bool]:
    """Return the environment capabilities relevant to pytest skips."""
    return {
        "requires_runners": _runners_exist(),
        "requires_qemu": _has_qemu(),
        "requires_local_tcp": _can_bind_localhost(),
        "requires_cross_compile": _has_any_cross_compiler(),
    }


def _collection_filters() -> dict[str, str]:
    """Return active env-driven collection filters."""
    return {
        "os": _env_filter("os"),
        "arch": _env_filter("arch"),
        "type": _env_filter("type"),
    }


def _skip_marker_reason(keyword: str) -> str:
    """Return the human-facing skip reason for one capability marker."""
    reasons = {
        "requires_runners": "Test runners not built. Run: bazel build //tests/runners/...",
        "requires_qemu": "QEMU user-static not installed.",
        "requires_local_tcp": "Local TCP sockets are unavailable in this environment.",
        "requires_cross_compile": "No Bootlin cross-compiler is discoverable.",
    }
    return reasons[keyword]


def _apply_capability_skips(
    items: list[pytest.Item],
    capabilities: dict[str, bool],
) -> None:
    """Skip tests whose declared infrastructure requirements are unavailable."""
    for item in items:
        for keyword, available in capabilities.items():
            if keyword in item.keywords and not available:
                item.add_marker(pytest.mark.skip(reason=_skip_marker_reason(keyword)))


def _item_filter_params(item: pytest.Item) -> tuple[str, str, str]:
    """Extract (type, os, arch) parameters from a collected item."""
    params = getattr(item, "callspec", None)
    if not params:
        return "", "", ""
    p = params.params
    param_os = p.get("target_os", "")
    param_arch = p.get("target_arch", "")
    param_type = p.get("blob_type", "")
    combo = p.get("payload_combo")
    if combo is not None:
        param_type, param_os, param_arch = combo
    return param_type, param_os, param_arch


def _apply_env_filters(items: list[pytest.Item], filters: dict[str, str]) -> None:
    """Skip parametrized items that do not match env-driven filters."""
    if not any(filters.values()):
        return
    for item in items:
        param_type, param_os, param_arch = _item_filter_params(item)
        for key, actual in (
            ("os", param_os),
            ("arch", param_arch),
            ("type", param_type),
        ):
            expected = filters[key]
            if expected and actual and actual != expected:
                item.add_marker(pytest.mark.skip(reason=f"Filtered: {key}!={expected}"))
