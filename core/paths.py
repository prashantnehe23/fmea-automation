"""
core/paths.py — B-042 (ADR-026): where runtime data lives.

By default runtime files sit next to the code (as before). Setting FMEA_DATA_DIR moves all of them
(database, settings, scan caches, per-workspace output) to one directory, so a container can mount
a single volume.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir(default: Path) -> Path:
    """The FMEA_DATA_DIR directory if set, otherwise *default*."""
    configured = os.environ.get("FMEA_DATA_DIR", "").strip()
    return Path(configured) if configured else default
