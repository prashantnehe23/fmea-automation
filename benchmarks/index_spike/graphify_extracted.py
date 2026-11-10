"""Graphify restricted to edges it tags EXTRACTED (see graphify.py)."""

import os
from pathlib import Path

from benchmarks.index_spike import graphify


def index_repo(repo: Path) -> dict:
    os.environ["SPIKE_GRAPHIFY_EXTRACTED_ONLY"] = "1"
    try:
        return graphify.index_repo(repo)
    finally:
        os.environ.pop("SPIKE_GRAPHIFY_EXTRACTED_ONLY", None)
