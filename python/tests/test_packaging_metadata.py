"""Packaging metadata regression tests for the PyPI-facing Python packages."""

from __future__ import annotations

import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_pyproject(package_dir: str) -> dict:
    pyproject = REPO_ROOT / package_dir / "pyproject.toml"
    return tomllib.loads(pyproject.read_text())


class TestPicblobsPackaging:
    def test_library_readme_is_not_blank(self) -> None:
        readme = REPO_ROOT / "python" / "README.md"
        assert readme.read_text().strip()

    def test_library_metadata_has_release_fields(self) -> None:
        project = _load_pyproject("python")["project"]

        assert project["readme"] == "README.md"
        assert project["classifiers"]
        assert project["keywords"]
        assert project["urls"]["Homepage"]
        assert project["urls"]["Documentation"]
        assert project["urls"]["Issues"]

    def test_library_wheel_excludes_dev_so_tree(self) -> None:
        pyproject = _load_pyproject("python")
        wheel_target = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

        assert wheel_target["packages"] == ["picblobs"]
        assert "picblobs/_blobs/**" in pyproject["tool"]["hatch"]["build"]["exclude"]
        assert "force-include" not in wheel_target


class TestPicblobsCliPackaging:
    def test_cli_readme_is_not_blank(self) -> None:
        readme = REPO_ROOT / "python_cli" / "README.md"
        assert readme.read_text().strip()

    def test_cli_metadata_has_release_fields(self) -> None:
        project = _load_pyproject("python_cli")["project"]

        assert project["readme"] == "README.md"
        assert project["classifiers"]
        assert project["keywords"]
        assert project["urls"]["Homepage"]
        assert project["urls"]["Documentation"]
        assert project["urls"]["Issues"]

    def test_cli_wheel_relies_on_package_tree_inclusion(self) -> None:
        wheel_target = _load_pyproject("python_cli")["tool"]["hatch"]["build"][
            "targets"
        ]["wheel"]

        assert wheel_target["packages"] == ["picblobs_cli"]
        assert "force-include" not in wheel_target
