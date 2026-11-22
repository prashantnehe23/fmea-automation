"""
core/actions.py — B-030 (ADR-018): corrective and preventive actions as one structured shape.

Urgency is an ordering hint (now / next / later) derived here from risk and kind. It is never a date,
a day range or a schedule; dates are the team's own planning, not something a model can know.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core.models import Action, RemediationPlan

CORRECTIVE_KINDS = ("code_fix", "containment", "config_change")
PREVENTIVE_KINDS = ("guardrail", "design_change", "monitoring", "runbook")
OWNER_ROLES = ("developer", "security", "sre", "product")
MAX_ACTIONS = 6

_HIGH = ("Critical", "High")
# kind -> (bands for Critical/High, Medium, Low)
_URGENCY = {
    "containment":   ("now", "now", "next"),
    "code_fix":      ("now", "next", "later"),
    "config_change": ("now", "next", "later"),
    "guardrail":     ("next", "later", "later"),
    "design_change": ("next", "later", "later"),
    "monitoring":    ("now", "next", "later"),
    "runbook":       ("next", "later", "later"),
}
_PATH = re.compile(r"[\w][\w./\\-]*\.(?:py|jsx?|tsx?|java|go|rb|php|cs|cpp|c|h|rs|kt|swift|sql|html|sh|ya?ml|json|tf|toml)\b")


def urgency_for(kind: str, priority: str) -> str:
    high, medium, low = _URGENCY.get(kind, _URGENCY["code_fix"])
    return high if priority in _HIGH else medium if priority == "Medium" else low


def _owner(value: Any, kind: str) -> str:
    words = set(re.findall(r"[a-z]+", str(value or "").lower()))
    for needle, role in (("sre", "sre"), ("devops", "sre"), ("ops", "sre"), ("platform", "sre"), ("infra", "sre"),
                         ("security", "security"), ("secops", "security"), ("developer", "developer"), ("dev", "developer"),
                         ("engineer", "developer"), ("product", "product"), ("owner", "product")):
        if needle in words:
            return role
    return "sre" if kind in ("monitoring", "runbook") else "developer"


def _kind(value: Any, allowed: tuple[str, ...], default: str) -> str:
    kind = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return kind if kind in allowed else default


def _items(raw: Any, side: str) -> list:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if isinstance(raw, dict):
        raw = raw.get("actions") or raw.get(side) or []
    return raw if isinstance(raw, list) else []


def coerce_actions(raw: Any, *, side: str, failure, risk, default_kind: str | None = None) -> list[Action]:
    """Tidy a model answer into at most MAX_ACTIONS valid actions. Anything unusable is dropped, never raised."""
    allowed = CORRECTIVE_KINDS if side == "corrective" else PREVENTIVE_KINDS
    default = default_kind if default_kind in allowed else allowed[0] if side == "corrective" else "guardrail"
    found = _PATH.search(getattr(failure, "evidence", None) or "")
    fallback_target = found.group(0) if found and side == "corrective" else ""   # a preventive action is not about that file
    priority = getattr(risk, "priority", "") or ""
    out: list[Action] = []
    for item in _items(raw, side):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict) or len(out) >= MAX_ACTIONS:
            continue
        kind = _kind(item.get("kind"), allowed, default)
        detail = str(item.get("detail") or item.get("description") or "").strip()
        title = str(item.get("title") or item.get("action") or "").strip() or detail[:80] or kind.replace("_", " ")
        out.append(Action(
            id=f"{'c' if side == 'corrective' else 'p'}{len(out) + 1}",
            title=title[:160], detail=detail[:1000], kind=kind,
            target=str(item.get("target") or fallback_target).strip()[:200],
            verification=str(item.get("verification") or "").strip()[:400],
            owner_role=_owner(item.get("owner_role") or item.get("owner"), kind),
            urgency=urgency_for(kind, priority)))
    return out


def plan_actions(plan: RemediationPlan) -> tuple[list[Action], list[Action]]:
    """The plan's corrective and preventive actions. Plans stored before B-030 carry only text lists:
    fixes become corrective actions, monitoring and resilience upgrades become preventive ones."""
    if plan.corrective or plan.preventive:
        return list(plan.corrective), list(plan.preventive)
    corrective = [Action(id=f"c{i}", title=t, kind="code_fix", urgency="next") for i, t in enumerate(plan.fixes, 1)]
    preventive = [Action(id=f"p{i}", title=t, kind=k, owner_role="sre" if k == "monitoring" else "developer", urgency="next")
                  for i, (t, k) in enumerate([(m, "monitoring") for m in plan.monitoring]
                                             + [(u, "design_change") for u in plan.resilience_upgrades], 1)]
    return corrective, preventive
