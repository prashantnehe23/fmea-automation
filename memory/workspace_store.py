"""
Workspace-aware wrappers for cache, learning memory, and memory stats.

When a WorkspaceContext is provided, all storage is scoped to:
  memory/workspaces/{customer_slug}/{project_slug}/

When no workspace is provided, falls back to the global paths in
memory/analysis_cache.py and memory/learning_memory.py (backward compat).

Core learning (anonymised vulnerability category patterns — no customer data)
is always updated alongside workspace learning and lives in:
  memory/core/learning_memory.json
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from core.paths import data_dir
from core.root_cause import category_for
from typing import Any

_MEMORY_ROOT = data_dir(Path(__file__).resolve().parent)
_CORE_DIR = _MEMORY_ROOT / "core"


def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ── Fingerprinting (shared) ────────────────────────────────────────────────────

def _fingerprint(code: str) -> str:
    normalized = "\n".join(line.rstrip() for line in code.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


# ── Cache ──────────────────────────────────────────────────────────────────────

def _cache_path(ws) -> Path:
    if ws is None:
        return _MEMORY_ROOT / "analysis_cache.json"
    from core.workspace import workspace_dir
    return workspace_dir(ws) / "analysis_cache.json"


def _serialize(result: dict) -> dict:
    """Pydantic models → plain dicts for JSON storage."""
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


def _deserialize(data: dict) -> dict:
    from core.models import (
        ControlAssessment, FailureMode, RemediationPlan, RiskScore, RootCause,
        ScenarioLinkageReport, SystemContext, ValidationResult,
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


def get_cached_result(code: str, ws=None) -> dict | None:
    fp = _fingerprint(code)
    path = _cache_path(ws)
    if not path.exists():
        return None
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    entry = cache.get(fp)
    if entry and "result" in entry:
        try:
            result = _deserialize(entry["result"])
            result["from_cache"] = True
            result["fingerprint"] = fp
            result["cached_at"] = entry.get("timestamp", "unknown")
            return result
        except Exception:
            return None
    return None


def cache_result(code: str, result: dict, ws=None) -> None:
    fp = _fingerprint(code)
    path = _ensure(_cache_path(ws))
    cache: dict = {}
    if path.exists():
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    cache[fp] = {
        "fingerprint": fp,
        "timestamp": datetime.now().isoformat(),
        "result": _serialize(result),
    }
    path.write_text(json.dumps(cache, indent=2, default=str), encoding="utf-8")


# ── Learning memory ────────────────────────────────────────────────────────────

def _ws_learning_path(ws) -> Path:
    if ws is None:
        return _MEMORY_ROOT / "learning_memory.json"
    from core.workspace import workspace_dir
    return workspace_dir(ws) / "learning_memory.json"


def _core_learning_path() -> Path:
    _CORE_DIR.mkdir(parents=True, exist_ok=True)
    return _CORE_DIR / "learning_memory.json"


def _load_json(path: Path, default: dict) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {**default, **data}
        except Exception:
            pass
    return dict(default)


def _save_json(path: Path, data: dict) -> None:
    _ensure(path).write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


_EMPTY_MEMORY: dict = {
    "version": 1,
    "aggression_level": 1,
    "total_analyses": 0,
    "patterns": [],
    "global_attack_chains": [],
}

_AGGRESSION_DESCRIPTIONS = {
    1: "Be thorough and systematic. Cover all standard OWASP categories.",
    2: "Be thorough. Probe for non-obvious chained weaknesses across boundaries.",
    3: (
        "Be rigorous. Challenge every assumption about trust and input validation. "
        "Look for combinations of weaknesses that together lead to a larger impact."
    ),
    4: (
        "Be highly rigorous. Consider how an informed user with bad intent could misuse the system. "
        "Examine race conditions, state corruption, and privilege escalation paths."
    ),
    5: (
        "Be exhaustive. Look for edge cases others miss. "
        "Consider how low-severity weaknesses combine into severe impacts. "
        "Treat no assumption as safe."
    ),
}


def _update_memory_patterns(memory: dict, failures: list, risks: list, domains: dict | None = None) -> dict:
    """Mutate and return memory with updated pattern counts/chains."""
    memory["total_analyses"] = memory.get("total_analyses", 0) + 1

    thresholds = [(20, 5), (10, 4), (5, 3), (2, 2), (0, 1)]
    for threshold, level in thresholds:
        if memory["total_analyses"] >= threshold:
            memory["aggression_level"] = level
            break

    patterns_by_key: dict[str, dict] = {
        p["pattern_key"]: p for p in memory.get("patterns", [])
    }

    for failure, risk in zip(failures, risks):
        category = category_for((domains or {}).get(failure.failure_mode))
        key = category
        new_steps = [s for s in failure.attack_chain if len(s) > 10]

        if key in patterns_by_key:
            p = patterns_by_key[key]
            p["frequency"] += 1
            p["last_seen"] = datetime.now().isoformat()
            n = p["frequency"]
            p["avg_severity"] = round((p["avg_severity"] * (n - 1) + risk.severity) / n, 1)
            p["avg_occurrence"] = round((p["avg_occurrence"] * (n - 1) + risk.occurrence) / n, 1)
            p["avg_detection"] = round((p["avg_detection"] * (n - 1) + risk.detection) / n, 1)
            p["avg_rpn"] = round(p["avg_severity"] * p["avg_occurrence"] * p["avg_detection"], 1)
            existing = p.get("example_attack_steps", [])
            for step in new_steps:
                if step not in existing:
                    existing.append(step)
            p["example_attack_steps"] = existing[-10:]
            names = p.get("seen_failure_modes", [])
            if failure.failure_mode not in names:
                names.append(failure.failure_mode)
            p["seen_failure_modes"] = names[-5:]
        else:
            patterns_by_key[key] = {
                "pattern_key": key,
                "category": category,
                "frequency": 1,
                "avg_severity": float(risk.severity),
                "avg_occurrence": float(risk.occurrence),
                "avg_detection": float(risk.detection),
                "avg_rpn": float(risk.rpn),
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "example_attack_steps": new_steps[:10],
                "seen_failure_modes": [failure.failure_mode],
            }

    memory["patterns"] = list(patterns_by_key.values())

    global_chains = memory.get("global_attack_chains", [])
    for failure in failures:
        for step in failure.attack_chain:
            if step not in global_chains and len(step) > 15:
                global_chains.append(step)
    memory["global_attack_chains"] = global_chains[-50:]
    return memory


def get_learning_context(ws=None) -> str:
    """
    Build the learning-context block injected into the saboteur prompt.
    Merges core learning + workspace learning (if opted in).
    Returns "" on first run (no history yet).
    """
    # Workspace memory (full patterns with failure mode names)
    ws_memory = _load_json(_ws_learning_path(ws), _EMPTY_MEMORY)

    # Core memory (anonymised — just category frequencies)
    core_memory = _load_json(_core_learning_path(), _EMPTY_MEMORY)

    # Use workspace memory as primary; fall back to core if empty
    memory = ws_memory if ws_memory["total_analyses"] > 0 else core_memory

    if memory["total_analyses"] == 0:
        return ""

    aggression = memory["aggression_level"]
    aggression_desc = _AGGRESSION_DESCRIPTIONS.get(aggression, _AGGRESSION_DESCRIPTIONS[1])

    patterns = sorted(memory.get("patterns", []), key=lambda p: -p["frequency"])
    top_patterns = patterns[:6]

    pattern_lines = "\n".join(
        f"  \u2022 {p['category'].replace('_', ' ').title()} "
        f"(seen {p['frequency']}x, avg RPN {p['avg_rpn']:.0f}): "
        + (p["seen_failure_modes"][0] if p.get("seen_failure_modes") else "recurring pattern")
        for p in top_patterns
    )

    chain_samples = memory.get("global_attack_chains", [])[-6:]
    chain_lines = "\n".join(f"  \u2022 {s}" for s in chain_samples) if chain_samples else "  (none yet)"

    return f"""
=== LEARNING CONTEXT (from {memory['total_analyses']} prior analyses) ===
Aggression level: {aggression}/5 \u2014 {aggression_desc}

High-frequency vulnerability categories to examine closely:
{pattern_lines if pattern_lines else '  (no patterns yet)'}

Known abuse-path patterns to extend with new findings:
{chain_lines}

Instructions:
- FIRST verify whether any of the above categories appear in this code.
- THEN look for NEW, novel failure modes not seen before.
- If aggression >= 3: Consider how several low-severity weaknesses combine into one high-impact failure.
- If aggression >= 4: Check whether each default configuration is safe.
- Do NOT duplicate failure modes that are trivially identical to known patterns;
  instead EXTEND them with code-specific details.
=== END LEARNING CONTEXT ===
""".strip()


def update_from_run(failures: list, risks: list, ws=None, domains: dict | None = None) -> None:
    """
    Update workspace learning (if opted in) and core anonymised patterns.
    Called after every successful FMEA pipeline run.
    """
    # ── Workspace learning (full patterns, opt-in) ───────────────────────────
    if ws is None or ws.customer_learning:
        ws_path = _ws_learning_path(ws)
        ws_memory = _load_json(ws_path, dict(_EMPTY_MEMORY))
        ws_memory = _update_memory_patterns(ws_memory, failures, risks, domains)
        _save_json(ws_path, ws_memory)

    # ── Core learning (anonymised category-level stats only) ──────────────────
    core_path = _core_learning_path()
    core_memory = _load_json(core_path, dict(_EMPTY_MEMORY))

    # Only update category frequencies and aggression — no failure_mode names
    core_memory["total_analyses"] = core_memory.get("total_analyses", 0) + 1
    thresholds = [(20, 5), (10, 4), (5, 3), (2, 2), (0, 1)]
    for threshold, level in thresholds:
        if core_memory["total_analyses"] >= threshold:
            core_memory["aggression_level"] = level
            break

    patterns_by_key: dict[str, dict] = {
        p["pattern_key"]: p for p in core_memory.get("patterns", [])
    }
    for failure, risk in zip(failures, risks):
        category = category_for((domains or {}).get(failure.failure_mode))
        if category in patterns_by_key:
            p = patterns_by_key[category]
            p["frequency"] += 1
            n = p["frequency"]
            p["avg_severity"] = round((p["avg_severity"] * (n - 1) + risk.severity) / n, 1)
            p["avg_occurrence"] = round((p["avg_occurrence"] * (n - 1) + risk.occurrence) / n, 1)
            p["avg_detection"] = round((p["avg_detection"] * (n - 1) + risk.detection) / n, 1)
            p["avg_rpn"] = round(p["avg_severity"] * p["avg_occurrence"] * p["avg_detection"], 1)
        else:
            patterns_by_key[category] = {
                "pattern_key": category,
                "category": category,
                "frequency": 1,
                "avg_severity": float(risk.severity),
                "avg_occurrence": float(risk.occurrence),
                "avg_detection": float(risk.detection),
                "avg_rpn": float(risk.rpn),
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
            }

    core_memory["patterns"] = list(patterns_by_key.values())
    _save_json(core_path, core_memory)


def get_memory_stats(ws=None) -> dict[str, Any]:
    """Summary dict for dashboard display."""
    memory = _load_json(_ws_learning_path(ws), _EMPTY_MEMORY)
    if memory["total_analyses"] == 0:
        memory = _load_json(_core_learning_path(), _EMPTY_MEMORY)
    patterns = sorted(memory.get("patterns", []), key=lambda p: -p["frequency"])
    return {
        "total_analyses": memory["total_analyses"],
        "aggression_level": memory["aggression_level"],
        "known_categories": len(patterns),
        "top_patterns": patterns[:5],
        "global_chain_count": len(memory.get("global_attack_chains", [])),
    }
