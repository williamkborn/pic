#!/usr/bin/env python3
"""Validate built Python distribution artifacts for one package."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path


def _find_one(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one match for {pattern!r}, got {matches}")
    return matches[0]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _check_wheel_tag(names: list[str], wheel: zipfile.ZipFile) -> None:
    dist_info = next(
        (name for name in names if name.endswith(".dist-info/WHEEL")),
        None,
    )
    _require(dist_info is not None, "wheel metadata file is missing")
    metadata = wheel.read(dist_info).decode()
    _require("Tag: py3-none-any" in metadata, "wheel is not tagged py3-none-any")


def _check_picblobs(names: list[str]) -> None:
    blob_count = sum(name.startswith("picblobs/blobs/") for name in names)
    bin_count = sum(
        name.startswith("picblobs/blobs/") and name.endswith(".bin") for name in names
    )
    json_count = sum(
        name.startswith("picblobs/blobs/") and name.endswith(".json") for name in names
    )
    _require(
        "picblobs/manifest.json" in names,
        "picblobs wheel is missing manifest.json",
    )
    _require(blob_count > 0, "picblobs wheel contains no extracted blobs")
    _require(bin_count > 0, "picblobs wheel contains no extracted .bin payloads")
    _require(json_count > 0, "picblobs wheel contains no extracted .json metadata")
    _require(
        not any(name.startswith("picblobs/_blobs/") for name in names),
        "picblobs wheel should not include staged .so blobs",
    )
    _require(
        not any(name.startswith("picblobs/_runners/") for name in names),
        "picblobs wheel should not include runner binaries",
    )
    print(
        f"picblobs wheel ok: {blob_count} blob artifacts "
        f"({bin_count} .bin, {json_count} .json)"
    )


def _check_picblobs_cli(names: list[str]) -> None:
    runner_count = sum(name.startswith("picblobs_cli/_runners/") for name in names)
    _require(runner_count > 0, "picblobs-cli wheel contains no bundled runners")
    _require(
        not any(name.startswith("picblobs_cli/_blobs/") for name in names),
        "picblobs-cli wheel should not include blob payloads",
    )
    print(f"picblobs-cli wheel ok: {runner_count} runner artifacts")


def _check_sdist(path: Path, package: str, version: str | None) -> None:
    prefix = (
        f"{package.replace('-', '_')}-{version}"
        if version
        else package.replace("-", "_")
    )
    with tarfile.open(path, "r:gz") as sdist:
        names = sdist.getnames()
    _require(
        any(name.endswith("pyproject.toml") for name in names),
        "sdist is missing pyproject.toml",
    )
    if version:
        _require(
            path.name.startswith(prefix),
            f"sdist filename {path.name!r} does not start with {prefix!r}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate built Python distributions")
    parser.add_argument("package", choices=("picblobs", "picblobs-cli"))
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--expected-version")
    args = parser.parse_args()

    wheel = _find_one(args.dist_dir, "*.whl")
    sdist = _find_one(args.dist_dir, "*.tar.gz")

    if args.expected_version:
        expected_prefix = f"{args.package.replace('-', '_')}-{args.expected_version}"
        _require(
            wheel.name.startswith(expected_prefix),
            f"wheel filename {wheel.name!r} does not start with {expected_prefix!r}",
        )

    with zipfile.ZipFile(wheel) as built_wheel:
        names = built_wheel.namelist()
        _check_wheel_tag(names, built_wheel)
        if args.package == "picblobs":
            _check_picblobs(names)
        else:
            _check_picblobs_cli(names)

    _check_sdist(sdist, args.package, args.expected_version)
    print(f"sdist ok: {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
