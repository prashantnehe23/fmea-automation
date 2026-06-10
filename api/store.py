"""
api/store.py — In-memory result stores shared across routers.

Both /api/scan and /api/github/scan produce scan results that
/api/remediate needs to consume.  A single neutral module prevents
circular imports between those routers.
"""

from __future__ import annotations

import itertools
from typing import Any

from api.schemas import WorkspaceIn
from core.workspace import WorkspaceContext

# ── ID generators (reset on server restart — fine for a local tool) ──────────

_scan_id_gen = itertools.count(1)
_rem_id_gen  = itertools.count(1)

def next_scan_id() -> int:
    return next(_scan_id_gen)

def next_rem_id() -> int:
    return next(_rem_id_gen)

# ── Stores ────────────────────────────────────────────────────────────────────

# scan_id → {"result": dict, "code": str, "workspace": WorkspaceIn | None}
scan_store: dict[int, dict[str, Any]] = {}

# remediation_id → list[dict]
remediation_store: dict[int, list[dict[str, Any]]] = {}

# ── Shared helpers ────────────────────────────────────────────────────────────

def build_workspace(ws_in: WorkspaceIn) -> WorkspaceContext:
    """Convert a WorkspaceIn request model to a WorkspaceContext dataclass."""
    return WorkspaceContext(
        customer=ws_in.customer,
        project=ws_in.project,
        function=ws_in.function,
        business_tier=ws_in.business_tier,
        user_type=ws_in.user_type,
        business_context=ws_in.business_context,
        customer_learning=ws_in.customer_learning,
    )
