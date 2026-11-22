"""
core/root_cause.py — B-029 (ADR-016): the root-cause domains, read from a registry file, and tidying of model answers.

The rubric is data (`root_cause_domains.json`): a new domain is a new entry there, with no code change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.cwe import normalise_cwe
from core.models import RootCause

REGISTRY_PATH = Path(__file__).with_name("root_cause_domains.json")
UNCLASSIFIED = "unclassified"


_cache: dict = {}


def domains() -> list[dict]:
    """The registry's domains, re-read only when the file changes. A malformed registry fails here, with its path."""
    key = (str(REGISTRY_PATH), REGISTRY_PATH.stat().st_mtime_ns)
    if _cache.get("key") != key:
        try:
            found = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["domains"]
            assert found and all(d["id"] and d["label"] and d["rubric"] for d in found)
        except (ValueError, KeyError, TypeError, AssertionError) as exc:
            raise ValueError(f"root-cause registry {REGISTRY_PATH} is malformed") from exc
        _cache.update(key=key, value=found)
    return _cache["value"]


def label(domain: str | None) -> str:
    for d in domains():
        if d["id"] == domain:
            return d["label"]
    return "Not classified"


def category_for(domain: str | None) -> str:
    """The learning-memory category of a finding: its root-cause domain."""
    return domain or UNCLASSIFIED


def unclassified(failure_mode: str) -> RootCause:
    return RootCause(failure_mode=failure_mode)


def _domain_id(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    for d in domains():
        if text in (d["id"], d["label"].lower()):
            return d["id"]
    return None


def _text(value: Any, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def coerce_root_cause(raw: Any, failure_mode: str) -> RootCause:
    """An unusable answer, or an unknown primary domain, is 'unclassified' with no confidence; it never raises."""
    if not isinstance(raw, dict):
        return unclassified(failure_mode)
    cwe = normalise_cwe(raw.get("cwe"))
    primary = _domain_id(raw.get("primary") or raw.get("primary_domain") or raw.get("domain"))
    if primary is None:
        return RootCause(failure_mode=failure_mode, cwe=cwe)
    others = raw.get("contributing") or raw.get("contributing_domains") or []
    contributing: list[str] = []
    for value in others if isinstance(others, list) else []:
        d = _domain_id(value)
        if d and d != primary and d not in contributing:
            contributing.append(d)
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 0.0
    return RootCause(failure_mode=failure_mode, primary=primary, contributing=contributing,
                     symptom=_text(raw.get("symptom")), proximate_cause=_text(raw.get("proximate_cause")),
                     root_cause=_text(raw.get("root_cause")), confidence=round(confidence, 2), cwe=cwe)
