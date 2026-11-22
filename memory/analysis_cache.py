"""
Analysis cache: store FMEA results keyed by a code fingerprint (SHA-256).
On cache hit the full pipeline is skipped; only new/modified code causes re-analysis.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from core.paths import data_dir
from typing import Any

CACHE_PATH = data_dir(Path(__file__).parent) / "analysis_cache.json"


# ── Fingerprinting ──────────────────────────────────────────────────────────────

def get_fingerprint(code: str) -> str:
    """Return a 16-char SHA-256 prefix of the normalised source code."""
    normalized = "\n".join(line.rstrip() for line in code.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


# ── Serialisation helpers ───────────────────────────────────────────────────────

def _serialize_result(result: dict) -> dict:
    """Convert Pydantic models in the result dict to plain dicts for JSON storage."""
    out: dict[str, Any] = {}
    for key, val in result.items():
        if key in ("from_cache", "fingerprint"):
            out[key] = val
        elif hasattr(val, "model_dump"):
            out[key] = val.model_dump()
        elif isinstance(val, list):
            out[key] = [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in val
            ]
        else:
            out[key] = val
    return out


def _deserialize_result(data: dict) -> dict:
    """Reconstruct Pydantic models from a cached plain-dict result."""
    from core.models import (
        ControlAssessment,
        FailureMode,
        RemediationPlan,
        RiskScore,
        RootCause,
        ScenarioLinkageReport,
        SystemContext,
        ValidationResult,
    )

    result: dict[str, Any] = {}

    if "context" in data:
        result["context"] = SystemContext(**data["context"])
    if "failures" in data:
        result["failures"] = [FailureMode(**f) for f in data["failures"]]
    if "controls" in data:
        result["controls"] = [ControlAssessment(**c) for c in data["controls"]]
    if "risks" in data:
        result["risks"] = [RiskScore(**r) for r in data["risks"]]
    if "remediations" in data:
        result["remediations"] = [RemediationPlan(**r) for r in data["remediations"]]
    if "root_causes" in data:
        result["root_causes"] = [RootCause(**r) for r in data["root_causes"]]
    if "scenario_linkage" in data:
        result["scenario_linkage"] = ScenarioLinkageReport(**data["scenario_linkage"])
    if "validations" in data:
        result["validations"] = [ValidationResult(**v) for v in data["validations"]]

    return result


# ── Cache I/O ───────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, default=str), encoding="utf-8")


# ── Public API ──────────────────────────────────────────────────────────────────

def get_cached_result(code: str) -> dict | None:
    """
    Return the deserialized FMEA result for this code, or None if not cached.
    The returned dict has Pydantic model instances (same shape as a fresh run).
    """
    fp = get_fingerprint(code)
    cache = _load_cache()
    entry = cache.get(fp)
    if entry and "result" in entry:
        try:
            result = _deserialize_result(entry["result"])
            result["from_cache"] = True
            result["fingerprint"] = fp
            result["cached_at"] = entry.get("timestamp", "unknown")
            return result
        except Exception:
            # Corrupt or incompatible cache entry — treat as miss
            return None
    return None


def cache_result(code: str, result: dict) -> None:
    """Serialize and persist a fresh FMEA result for this code fingerprint."""
    fp = get_fingerprint(code)
    cache = _load_cache()
    cache[fp] = {
        "fingerprint": fp,
        "timestamp": datetime.now().isoformat(),
        "result": _serialize_result(result),
    }
    _save_cache(cache)


def list_cached_entries() -> list[dict]:
    """Return metadata for all cached analyses (for dashboard display)."""
    cache = _load_cache()
    entries = []
    for fp, entry in cache.items():
        result_data = entry.get("result", {})
        failures = result_data.get("failures", [])
        entries.append({
            "fingerprint": fp,
            "timestamp": entry.get("timestamp", ""),
            "failure_count": len(failures),
        })
    return sorted(entries, key=lambda e: e["timestamp"], reverse=True)
