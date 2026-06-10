"""
api/schemas.py — Pydantic request/response models and result serialisation.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from pydantic import BaseModel


# ── Request models ────────────────────────────────────────────────────────────

class WorkspaceIn(BaseModel):
    customer: str
    project: str
    function: str = ""
    business_tier: str = "Tier 1"
    user_type: str = "external_customers"
    business_context: str = ""
    customer_learning: bool = True


class ScanRequest(BaseModel):
    code: str
    workspace: WorkspaceIn | None = None
    max_failure_modes: int = 7
    force_rerun: bool = False


class RemediateRequest(BaseModel):
    scan_id: int


# ── Serialisation ─────────────────────────────────────────────────────────────

def _to_jsonable(obj: Any) -> Any:
    """Recursively convert Pydantic models and dataclasses to JSON-safe types."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    # numpy arrays are not JSON-safe; skip (embeddings never go to the frontend)
    try:
        import numpy as np  # type: ignore
        if isinstance(obj, np.ndarray):
            return None
    except ImportError:
        pass
    return obj


def serialize_result(result: dict) -> dict:
    """
    Convert a run_fmea() result dict to a fully JSON-serialisable dict.

    Handles Pydantic models (model_dump), dataclasses (asdict), numpy arrays
    (dropped), and plain Python primitives.
    """
    out: dict[str, Any] = {}
    for k, v in result.items():
        if k == "workspace" and v is not None and dataclasses.is_dataclass(v):
            out[k] = dataclasses.asdict(v)
        else:
            out[k] = _to_jsonable(v)
    return out
