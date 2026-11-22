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
    if isinstance(d.get("source"), str) and d["source"]:
        out["source"] = d["source"][:100]
    if d.get("cwe"):
        from core.cwe import normalise_cwe
        out["cwe"] = normalise_cwe(d["cwe"])
    if isinstance(d.get("also_reported_by"), list):
        out["also_reported_by"] = [str(x)[:80] for x in d["also_reported_by"]][:10]
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
