"""pytest configuration and shared fixtures for picblobs tests."""

from __future__ import annotations

import os
import shutil
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


# --- Environment-based filters (set by `picblobs test --os/--arch/--type`) ---

def _env_filter(key: str) -> str:
    return os.environ.get(f"PICBLOBS_TEST_{key.upper()}", "")


# --- Fixtures ---


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def blob_dir() -> Path:
    """Path to built .so blob files."""
    d = BAZEL_BIN / "src" / "blob"
    return d


@pytest.fixture(scope="session")
def runner_dir() -> Path:
    """Path to built test runner binaries."""
    d = BAZEL_BIN / "tests" / "runners"
    return d


@pytest.fixture(scope="session")
def runners_available(runner_dir: Path) -> bool:
    """True if test runners have been built."""
    return (runner_dir / "linux" / "runner").exists()


@pytest.fixture(scope="session")
def qemu_available() -> bool:
    """True if qemu-x86_64-static is on PATH."""
    return shutil.which("qemu-x86_64-static") is not None


# --- Markers ---

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "requires_runners: test needs compiled C test runners")
    config.addinivalue_line("markers", "requires_qemu: test needs QEMU user-static")
    config.addinivalue_line("markers", "requires_blobs: test needs built .so blobs")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item],
) -> None:
    """Auto-skip tests based on available infrastructure."""
    runners_exist = (BAZEL_BIN / "tests" / "runners" / "linux" / "runner").exists()
    has_qemu = shutil.which("qemu-x86_64-static") is not None

    # Environment-based filters.
    filter_os = _env_filter("os")
    filter_arch = _env_filter("arch")
    filter_type = _env_filter("type")

    for item in items:
        if "requires_runners" in item.keywords and not runners_exist:
            item.add_marker(pytest.mark.skip(
                reason="Test runners not built. Run: bazel build //tests/runners/...",
            ))

        if "requires_qemu" in item.keywords and not has_qemu:
            item.add_marker(pytest.mark.skip(
                reason="QEMU user-static not installed.",
            ))

        # Apply env-based filters to parametrized tests.
        if filter_os or filter_arch or filter_type:
            params = getattr(item, "callspec", None)
            if params:
                p = params.params
                if filter_os and p.get("target_os", "") != filter_os:
                    item.add_marker(pytest.mark.skip(reason=f"Filtered: os!={filter_os}"))
                if filter_arch and p.get("target_arch", "") != filter_arch:
                    item.add_marker(pytest.mark.skip(reason=f"Filtered: arch!={filter_arch}"))
                if filter_type and p.get("blob_type", "") != filter_type:
                    item.add_marker(pytest.mark.skip(reason=f"Filtered: type!={filter_type}"))
