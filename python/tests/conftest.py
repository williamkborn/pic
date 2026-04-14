"""pytest configuration and shared fixtures for picblobs tests."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest


def _project_root() -> Path:
    """Find the project root (directory containing MODULE.bazel)."""
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / "MODULE.bazel").exists():
            return parent
    return Path.cwd()


PROJECT_ROOT = _project_root()
BAZEL_BIN = PROJECT_ROOT / "bazel-bin"
_PACKAGE_RUNNERS = PROJECT_ROOT / "python" / "picblobs" / "_runners"
_BAZEL_RUNNER_PATHS = (
    BAZEL_BIN / "tests" / "runners" / "linux" / "runner.bin",
    BAZEL_BIN / "tests" / "runners" / "linux" / "runner",
)

# Import the registry for cross-arch parametrization.
sys.path.insert(0, str(PROJECT_ROOT))
from tools.registry import ARCHITECTURES, OPERATING_SYSTEMS, all_platforms

sys.path.pop(0)

# Import payload defs (same directory).
# payload_defs lives in the same directory as this conftest.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from payload_defs import all_payload_combos  # noqa: E402

sys.path.pop(0)


def _runners_exist() -> bool:
    if any(_PACKAGE_RUNNERS.rglob("runner")):
        return True
    return any(p.exists() for p in _BAZEL_RUNNER_PATHS)


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
    return shutil.which("qemu-x86_64-static") is not None


# ============================================================
# Markers
# ============================================================


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "requires_runners: test needs compiled C test runners"
    )
    config.addinivalue_line("markers", "requires_qemu: test needs QEMU user-static")
    config.addinivalue_line("markers", "requires_blobs: test needs built .so blobs")


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Auto-skip tests based on available infrastructure."""
    runners_exist = _runners_exist()
    has_qemu = shutil.which("qemu-x86_64-static") is not None

    # Environment-based filters.
    filter_os = _env_filter("os")
    filter_arch = _env_filter("arch")
    filter_type = _env_filter("type")

    for item in items:
        if "requires_runners" in item.keywords and not runners_exist:
            item.add_marker(
                pytest.mark.skip(
                    reason="Test runners not built. Run: bazel build //tests/runners/...",
                )
            )

        if "requires_qemu" in item.keywords and not has_qemu:
            item.add_marker(
                pytest.mark.skip(
                    reason="QEMU user-static not installed.",
                )
            )

        # Apply env-based filters to parametrized tests.
        if filter_os or filter_arch or filter_type:
            params = getattr(item, "callspec", None)
            if params:
                p = params.params

                # Support both individual params and tuple-based payload_combo.
                param_os = p.get("target_os", "")
                param_arch = p.get("target_arch", "")
                param_type = p.get("blob_type", "")

                # Extract from payload_combo tuple if present.
                combo = p.get("payload_combo")
                if combo is not None:
                    param_type, param_os, param_arch = combo

                if filter_os and param_os and param_os != filter_os:
                    item.add_marker(
                        pytest.mark.skip(reason=f"Filtered: os!={filter_os}")
                    )
                if filter_arch and param_arch and param_arch != filter_arch:
                    item.add_marker(
                        pytest.mark.skip(reason=f"Filtered: arch!={filter_arch}")
                    )
                if filter_type and param_type and param_type != filter_type:
                    item.add_marker(
                        pytest.mark.skip(reason=f"Filtered: type!={filter_type}")
                    )
