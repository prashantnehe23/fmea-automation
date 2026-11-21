"""
core/findings.py — B-031 (ADR-019): finding identity and lifecycle states.

Identity: a hash of the code the finding points at (its evidence quote, with file paths, line numbers
and quoting stripped), not of its name. A pure rename of the scenario text or a move of the file keeps
the same identity; embedding similarity (memory/scenario_registry.py) remains the fallback when the
quote itself changes. The threat class joins the hash when the discovery engine (B-028) supplies one.

Lifecycle:
  new            first reported
  confirmed      seen again by a later scan
  fix_candidate  a later scan did not reproduce it: shown for confirmation, never silently dropped or kept
  fixed          a person confirmed the fix
  regressed      reported again after it was fixed
  accepted       a person accepted the risk
  unresolved     could not be decided (set by the discovery engine, B-028)
"""

from __future__ import annotations

import hashlib
import re

STATES = ("new", "confirmed", "fix_candidate", "fixed", "regressed", "accepted", "unresolved")
# Findings the saboteur is asked to reproduce on every scan while their weakness is still in the code
EXPECTED_STATES = frozenset({"new", "confirmed", "regressed", "accepted", "unresolved"})
# States a scan may move to fix_candidate when it no longer reproduces the finding
FIXABLE_BY_SCAN = frozenset({"new", "confirmed", "regressed"})
# States a person may set by hand
MANUAL_TARGETS = frozenset({"fixed", "confirmed", "accepted"})

MIN_QUOTE_CHARS = 20
_PATH_REF = re.compile(r"[\w./\\-]+\.\w{1,8}:\d+(?:\s*-\s*\d+)?")
_LINE_PREFIX = re.compile(r"(?m)^\s*\d+\s*[|:]\s?")


def finding_identity(evidence: str | None) -> str | None:
    """Stable key from the code quote in a finding's evidence, or None when there is no usable quote."""
    if not evidence:
        return None
    text = _PATH_REF.sub(" ", evidence)
    text = _LINE_PREFIX.sub("", text)
    text = re.sub(r"[`'\"]", "", text).lower()
    text = re.sub(r"\s+", " ", text).strip(" .,;:-")
    if len(text) < MIN_QUOTE_CHARS:      # `return x` is not evidence of one particular weakness
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
