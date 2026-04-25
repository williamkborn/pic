#!/usr/bin/env python3
"""Shared path filtering helpers for repo quality tooling."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_excluded(path: Path, exclude: set[str]) -> bool:
    """Return True when a path is outside the repo or under an excluded segment."""
    try:
        rel_path = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return True
    return any(part in exclude for part in rel_path.parts)


def _iter_matching_files(
    path: Path,
    *,
    extensions: set[str],
    exclude: set[str],
) -> Iterable[Path]:
    if not path.exists() or is_excluded(path, exclude):
        return

    if path.is_file():
        if path.suffix in extensions:
            yield path
        return

    for child in path.rglob("*"):
        if not child.is_file():
            continue
        if child.suffix not in extensions:
            continue
        if is_excluded(child, exclude):
            continue
        yield child


def collect_files(
    inputs: Sequence[str],
    *,
    roots: Sequence[str],
    extensions: set[str],
    exclude: set[str],
) -> list[Path]:
    """Collect matching files from explicit inputs or from configured roots."""
    raw_paths = list(inputs) if inputs else list(roots)
    files: set[Path] = set()

    for raw_path in raw_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path = path.resolve()
        files.update(
            _iter_matching_files(path, extensions=extensions, exclude=exclude),
        )

    return sorted(files)
