"""picblobs-cli — click-based CLI + bundled runner binaries.

This package is a companion to ``picblobs``: the latter carries the blob
data and Python builder API, the former carries the cross-compiled test
runners and the ``picblobs-cli`` console script that puts them all
together under QEMU.

See ADR-026 and REQ-020 for the design rationale.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

try:
    from picblobs import __version__ as __picblobs_version__
except ImportError:  # pragma: no cover — picblobs is a hard dep
    __picblobs_version__ = "unknown"

__version__ = __picblobs_version__


def runners_dir() -> Path:
    """Return the on-disk path to the bundled ``_runners`` tree.

    Uses ``importlib.resources`` so the path resolves correctly both in
    source checkouts (where ``_runners`` is a filesystem directory) and
    inside an installed wheel.
    """
    return Path(str(importlib.resources.files(__name__) / "_runners"))


__all__ = ["__version__", "runners_dir"]
