"""
Normalize LLM JSON into shapes our Pydantic models expect.
Models vary keys (camelCase, wrappers, dict-instead-of-list); this layer absorbs that.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def _as_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, (int, float, bool)):
        return str(x)
    return json.dumps(x, ensure_ascii=False)


def _unwrap_top_level(d: dict[str, Any]) -> dict[str, Any]:
    """Lift inner dict from common wrapper keys (single merge)."""
    if not d:
        return {}
    for wrap in (
        "assessment",
        "resilience_assessment",
        "control_assessment",
        "audit",
        "result",
        "output",
        "data",
    ):
        inner = d.get(wrap)
        if isinstance(inner, dict):
            merged = {**inner, **{k: v for k, v in d.items() if k != wrap}}
            return merged
    return d


def _str_dict_values(d: Any) -> dict[str, str]:
    """Dict[str, str] with nested objects turned into strings (e.g. description blobs)."""
    if not isinstance(d, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in d.items():
        key = str(k).replace(" ", "_")
        if isinstance(v, str):
            out[key] = v
        elif isinstance(v, dict):
            desc = (
                v.get("description")
                or v.get("summary")
                or v.get("detail")
                or v.get("notes")
                or v.get("status")
            )
            if desc is not None and desc != "":
                extra = {kk: vv for kk, vv in v.items() if kk not in ("description", "summary", "detail", "notes", "status")}
                base = str(desc)
                if extra:
                    base = f"{base} ({json.dumps(extra, ensure_ascii=False)})"
                out[key] = base
            else:
                out[key] = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, list):
            out[key] = "; ".join(_as_str(x) for x in v)
        else:
            out[key] = str(v)
    return out


def _as_str_list(x: Any) -> list[str]:
    if x is None:
        return []
    if isinstance(x, list):
        out: list[str] = []
        for item in x:
            if isinstance(item, dict):
                out.append(json.dumps(item, ensure_ascii=False))
            else:
                out.append(str(item))
        return out
    if isinstance(x, str):
        return [s.strip() for s in re.split(r"[\n\r;•]+", x) if s.strip()]
    if isinstance(x, dict):
        return [f"{k}: {_as_str(v)}" for k, v in x.items()]
    return [str(x)]


def coerce_saboteur_json_root(raw: Any) -> list[dict[str, Any]]:
    """Accept array or object wrapping scenarios."""
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        d = raw
        for k in ("scenarios", "failures", "failure_modes", "items", "results", "data"):
            inner = d.get(k)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
        return [d]
    return []


def coerce_failure_mode_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    d = _unwrap_top_level(dict(raw))
    d = _unwrap_top_level(d)

    fm = (
        d.get("failure_mode")
        or d.get("failureMode")
        or d.get("title")
        or d.get("name")
        or "Unspecified failure"
    )
    chain = (
        d.get("attack_chain")
        or d.get("attackChain")
        or d.get("attack_steps")
        or d.get("steps")
        or []
    )
    if isinstance(chain, str):
        chain = [s.strip() for s in re.split(r"[\n\r;•]+", chain) if s.strip()]
    elif isinstance(chain, dict):
        chain = [f"{k}: {_as_str(v)}" for k, v in chain.items()]
    elif not isinstance(chain, list):
        chain = [str(chain)]
    chain = [str(x) for x in chain] if chain else ["Unknown attack path"]

    bi = d.get("business_impact") or d.get("businessImpact") or d.get("impact") or ""
    br = d.get("blast_radius") or d.get("blastRadius") or ""
    trig = d.get("trigger") or d.get("triggers") or ""
    if isinstance(trig, list):
        trig = "; ".join(str(x) for x in trig)
    ev = d.get("evidence") or d.get("Evidence")

    out: dict[str, Any] = {
        "failure_mode": str(fm),
        "attack_chain": chain,
        "business_impact": str(bi) if bi else "Not specified",
        "blast_radius": str(br) if br else "Not specified",
        "trigger": str(trig) if trig else "Not specified",
    }
    if ev is not None and str(ev).strip() != "":
        out["evidence"] = str(ev)
    return out


def coerce_control_assessment_payload(raw: Any, *, failure_mode_hint: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    d = _unwrap_top_level(dict(raw))
    d = _unwrap_top_level(d)

    fm = (
        d.get("failure_mode")
        or d.get("failureMode")
        or d.get("scenario")
        or d.get("scenario_name")
        or failure_mode_hint
    )

    ctr = d.get("controls")
    if not isinstance(ctr, dict):
        ctr = d.get("existing_controls") if isinstance(d.get("existing_controls"), dict) else {}
    if not isinstance(ctr, dict):
        ctr = {}

    maturity = (
        d.get("control_maturity")
        or d.get("controlMaturity")
        or d.get("maturity")
        or d.get("overall_maturity")
    )
    if maturity is None and isinstance(d.get("assessment"), dict):
        maturity = d["assessment"].get("control_maturity")
    if maturity is None and isinstance(d.get("meta"), dict):
        maturity = d["meta"].get("control_maturity")
    if isinstance(maturity, dict):
        maturity = (
            maturity.get("level")
            or maturity.get("rating")
            or maturity.get("label")
            or json.dumps(maturity, ensure_ascii=False)
        )
    if maturity is None or str(maturity).strip() == "":
        maturity = "moderate"

    gaps = (
        d.get("gaps")
        or d.get("gap")
        or d.get("identified_gaps")
        or d.get("gap_analysis")
        or d.get("control_gaps")
    )
    if isinstance(gaps, dict):
        gaps = _as_str_list(list(gaps.values()))
    else:
        gaps = _as_str_list(gaps)
    if not gaps:
        gaps = ["Model did not list gaps; treat controls as unverified."]

    return {
        "failure_mode": str(fm) if str(fm).strip() else failure_mode_hint,
        "controls": _str_dict_values(ctr),
        "control_maturity": str(maturity).strip().lower(),
        "gaps": gaps,
    }


def _coerce_roadmap_tasks(raw_tasks: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tasks, list):
        return []
    out: list[dict[str, Any]] = []
    for i, t in enumerate(raw_tasks):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("task_id") or t.get("id") or f"task_{i + 1}")
        title = str(t.get("title") or t.get("name") or "Implementation task")
        try:
            sd = int(t.get("start_day") or t.get("start") or 1)
        except (TypeError, ValueError):
            sd = 1
        try:
            ed = int(t.get("end_day") or t.get("end") or min(sd + 14, 90))
        except (TypeError, ValueError):
            ed = min(sd + 14, 90)
        sd = max(1, min(90, sd))
        ed = max(sd, min(90, ed))
        if ed < sd:
            sd, ed = ed, sd
        deps = t.get("depends_on") or t.get("dependencies") or []
        if isinstance(deps, str):
            deps = [d.strip() for d in deps.replace(";", ",").split(",") if d.strip()]
        elif not isinstance(deps, list):
            deps = []
        deps = [str(x) for x in deps]
        exp = bool(t.get("expedited") or t.get("critical") or t.get("fast_track"))
        note = str(t.get("implementation_note") or t.get("notes") or "")[:500]
        out.append(
            {
                "task_id": tid,
                "title": title,
                "start_day": sd,
                "end_day": ed,
                "depends_on": deps,
                "expedited": exp,
                "implementation_note": note,
            }
        )
    return out


def _synthetic_tasks_from_roadmap(
    road_map: dict[str, str], failure_mode_hint: str, expedited: bool
) -> list[dict[str, Any]]:
    """Fallback Gantt rows when the model omits roadmap_tasks."""
    tasks: list[dict[str, Any]] = []
    prev_tid: str | None = None
    for i, (phase, text) in enumerate(road_map.items()):
        m = re.search(r"(\d+)", str(phase))
        day = int(m.group(1)) if m else (i + 1) * 28
        start = max(1, day - 20)
        end = min(90, day + 10)
        tid = f"synth_{i}_{day}"
        note = text[:220] + ("…" if len(text) > 220 else "")
        tasks.append(
            {
                "task_id": tid,
                "title": f"{phase} — {failure_mode_hint[:50]}",
                "start_day": start,
                "end_day": end,
                "depends_on": [prev_tid] if prev_tid else [],
                "expedited": expedited and i == 0,
                "implementation_note": note,
            }
        )
        prev_tid = tid
    return tasks


def coerce_remediation_plan_payload(
    raw: Any,
    *,
    failure_mode_hint: str,
    risk: Optional[Any] = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    d = _unwrap_top_level(dict(raw))
    d = _unwrap_top_level(d)

    fm = d.get("failure_mode") or d.get("failureMode") or failure_mode_hint

    fixes = _as_str_list(d.get("fixes") or d.get("fix") or d.get("recommendations") or d.get("actions"))
    mon = _as_str_list(
        d.get("monitoring") or d.get("monitoring_recommendations") or d.get("observability")
    )
    res = _as_str_list(
        d.get("resilience_upgrades")
        or d.get("resilienceUpgrades")
        or d.get("upgrades")
        or d.get("hardening")
    )

    road = d.get("roadmap_90_day") or d.get("roadmap") or d.get("roadmap90") or d.get("ninety_day_plan")
    road_map: dict[str, str] = {}
    if isinstance(road, list):
        for i, item in enumerate(road):
            if isinstance(item, dict):
                day = item.get("day") or item.get("milestone") or item.get("phase") or f"step_{i}"
                act = item.get("action") or item.get("summary") or item.get("text") or json.dumps(item)
                road_map[str(day)] = str(act)
            else:
                road_map[f"step_{i}"] = str(item)
    elif isinstance(road, dict):
        for k, v in road.items():
            road_map[str(k)] = _as_str(v) if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False)
    if not road_map:
        road_map = {
            "Day 30": "Stabilize monitoring and highest-risk mitigations.",
            "Day 60": "Deploy resilience controls; narrow blast radius.",
            "Day 90": "Validate with tabletop or chaos testing.",
        }

    tasks = _coerce_roadmap_tasks(d.get("roadmap_tasks") or d.get("tasks") or d.get("gantt_tasks"))
    dep_notes = str(
        d.get("dependency_notes")
        or d.get("dependencies")
        or d.get("implementation_dependencies")
        or ""
    )[:2000]
    rpn_note = str(
        d.get("rpn_priority_note")
        or d.get("priority_note")
        or d.get("rpn_note")
        or ""
    )[:800]

    expedited = False
    if risk is not None:
        pr = getattr(risk, "priority", None) or ""
        expedited = str(pr) in ("Critical", "High")

    if not tasks:
        tasks = _synthetic_tasks_from_roadmap(road_map, failure_mode_hint, expedited)

    if not dep_notes and tasks:
        dep_notes = (
            "Tasks follow phase dependencies: complete earlier milestones before "
            "expanding scope; expedited items track higher RPN scenarios first."
        )

    if not rpn_note and risk is not None:
        pr = getattr(risk, "priority", "?")
        rpn = getattr(risk, "rpn", "?")
        rpn_note = (
            f"Remediation urgency follows RPN {rpn} ({pr}): higher scores front-load "
            "controls and monitoring in earlier days."
        )

    ffm = str(fm).strip() or failure_mode_hint or "Unspecified failure"
    return {
        "failure_mode": ffm,
        "fixes": fixes or ["Prioritize fixes from engineering review."],
        "monitoring": mon or ["Add metrics and alerts for this failure class."],
        "resilience_upgrades": res or ["Improve isolation, timeouts, and safe defaults."],
        "roadmap_90_day": road_map,
        "roadmap_tasks": tasks,
        "dependency_notes": dep_notes,
        "rpn_priority_note": rpn_note,
    }
