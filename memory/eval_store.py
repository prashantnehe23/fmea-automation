"""
Persist pipeline evaluation results and detect score drift.

Per-workspace history: memory/workspaces/{slug}/eval_history.json
Core anonymised history: memory/core/eval_history.json

Drift alert: any agent's score drops > 0.10 vs the average of the previous 3 runs,
or overall_passed flips from True to False.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_MEMORY_ROOT = Path(__file__).resolve().parent
_CORE_DIR = _MEMORY_ROOT / "core"


def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ws_eval_path(ws) -> Path:
    if ws is None:
        return _MEMORY_ROOT / "core" / "eval_history.json"
    from core.workspace import workspace_dir
    return workspace_dir(ws) / "eval_history.json"


def _core_eval_path() -> Path:
    _CORE_DIR.mkdir(parents=True, exist_ok=True)
    return _CORE_DIR / "eval_history.json"


def _load_history(path: Path) -> list[dict]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_history(path: Path, history: list[dict]) -> None:
    _ensure(path).write_text(
        json.dumps(history, indent=2, default=str), encoding="utf-8"
    )


# ── Public API ──────────────────────────────────────────────────────────────────

def append_eval(eval_result: Any, ws=None) -> None:
    """
    Persist a PipelineEval result.
    Writes to workspace eval_history.json and core eval_history.json (anonymised).
    """
    # Build serialisable record
    agent_scores = {e.agent: e.score for e in eval_result.agents}
    record = {
        "timestamp": datetime.now().isoformat(),
        "overall_passed": eval_result.overall_passed,
        "avg_score": round(sum(e.score for e in eval_result.agents) / max(len(eval_result.agents), 1), 3),
        "llm_calls": eval_result.llm_calls,
        "estimated_cost_usd": eval_result.estimated_cost_usd,
        "scenario_count": eval_result.scenario_count,
        "agent_scores": agent_scores,
        "summary": eval_result.summary,
    }

    # Workspace history (full detail)
    ws_path = _ws_eval_path(ws)
    ws_history = _load_history(ws_path)
    ws_history.append(record)
    _save_history(ws_path, ws_history)

    # Core history (same structure — no customer-identifiable data in eval records)
    if ws is not None:
        core_path = _core_eval_path()
        core_history = _load_history(core_path)
        core_history.append({k: v for k, v in record.items() if k not in ("summary",)})
        _save_history(core_path, core_history)


def get_eval_trend(ws=None, n: int = 10) -> list[dict]:
    """Return the last N eval records for the workspace (newest last)."""
    path = _ws_eval_path(ws)
    history = _load_history(path)
    return history[-n:]


def detect_drift(ws=None) -> list[str]:
    """
    Compare the latest eval to the average of the previous 3.
    Returns a list of human-readable alert strings (empty = no drift).
    """
    history = _load_history(_ws_eval_path(ws))
    if len(history) < 2:
        return []

    latest = history[-1]
    prev = history[-4:-1]  # up to 3 records before latest
    if not prev:
        return []

    alerts: list[str] = []

    # overall_passed flip
    prev_passed = all(r.get("overall_passed", True) for r in prev)
    if prev_passed and not latest.get("overall_passed", True):
        alerts.append("Pipeline overall_passed flipped to False — one or more agents now failing.")

    # Per-agent score drop
    for agent, latest_score in latest.get("agent_scores", {}).items():
        prev_scores = [r["agent_scores"].get(agent) for r in prev if "agent_scores" in r]
        prev_scores = [s for s in prev_scores if s is not None]
        if not prev_scores:
            continue
        avg_prev = sum(prev_scores) / len(prev_scores)
        drop = avg_prev - latest_score
        if drop > 0.10:
            alerts.append(
                f"{agent}: score dropped {drop:.2f} (was {avg_prev:.2f}, now {latest_score:.2f})."
            )

    return alerts
