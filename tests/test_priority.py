"""
tests/test_priority.py — B-034 phase 1: severity-aware prioritisation (ADR-020)

  AC1  S10/O2/D2 is High or above with a stated reason; S9/O1/D1 is High
  AC2  bands for non-catastrophic scores are unchanged
  AC3  exactly one priority implementation exists
  AC4  the validator cannot take a realistic finding's Severity from >= 9 to < 9
"""

import re
from pathlib import Path

import pytest

from core.models import RiskScore, ValidationResult
from core.priority import exploit_confirmed_from, guarded_severity, priority_for
from workflows.fmea_pipeline import apply_validation

ROOT = Path(__file__).resolve().parents[1]


# ── AC1 ───────────────────────────────────────────────────────────────────────

def test_catastrophic_severity_is_never_medium_and_says_why():
    p = priority_for(10, 2, 2)
    assert p.band == "High" and "severity 10 floor" in p.reason and "RPN 40" in p.reason
    assert priority_for(9, 1, 1).band == "High"
    assert priority_for(10, 3, 3).band == "High"          # the RPN-90 case from ADR-020


def test_severity_10_with_confirmed_exploit_and_weak_detection_is_critical():
    assert priority_for(10, 2, 6, exploit_confirmed=True).band == "Critical"
    assert "confirmed exploit" in priority_for(10, 2, 6, exploit_confirmed=True).reason
    assert priority_for(10, 2, 5, exploit_confirmed=True).band == "High"     # detection not weak enough
    assert priority_for(10, 2, 6, exploit_confirmed=False).band == "High"    # not confirmed
    assert priority_for(9, 2, 9, exploit_confirmed=True).band == "High"      # only severity 10 qualifies


# ── AC2 ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("s, o, d, band", [
    (5, 8, 5, "Medium"), (5, 8, 6, "High"), (8, 5, 5, "Medium"), (8, 5, 6, "High"),
    (8, 7, 7, "High"), (9, 9, 5, "Critical"), (1, 1, 1, "Medium"), (6, 9, 8, "Critical"),
])
def test_non_catastrophic_bands_follow_rpn(s, o, d, band):
    p = priority_for(s, o, d)
    assert p.band == band and p.reason.startswith(f"{band}: RPN {s * o * d}")


def test_rpn_boundaries():
    assert priority_for(5, 8, 5).band == "Medium"    # 200
    assert priority_for(5, 5, 8).band == "Medium"    # 200
    assert priority_for(3, 8, 9).band == "High"      # 216
    assert priority_for(8, 10, 5).band == "High"     # 400
    assert priority_for(9, 9, 5).band == "Critical"  # 405


# ── AC3 ───────────────────────────────────────────────────────────────────────

def test_only_core_priority_computes_a_band():
    """Fails if an inline RPN-band expression (or the old helper) reappears outside core/priority.py."""
    inline = re.compile(r"rpn\s*>\s*(400|200)|priority_for_rpn")
    offenders = []
    for folder in ("agents", "api", "core", "memory", "workflows"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.name == "priority.py":
                continue
            if inline.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"inline priority rule found in {offenders}; use core.priority.priority_for"


# ── AC4 ───────────────────────────────────────────────────────────────────────

def _risk(s, o, d):
    p = priority_for(s, o, d)
    return RiskScore(failure_mode="X", severity=s, occurrence=o, detection=d, rpn=s * o * d,
                     priority=p.band, priority_reason=p.reason, justification="j",
                     severity_rationale="r", occurrence_rationale="r", detection_rationale="r")


def _validation(**kw):
    return ValidationResult(failure_mode="X", **kw)


def test_validator_cannot_lower_a_realistic_catastrophic_severity():
    out = apply_validation(_risk(10, 3, 3), _validation(severity_adjustment=-2, is_realistic=True))
    assert out.severity == 9 and out.priority == "High"
    out = apply_validation(_risk(9, 3, 3), _validation(severity_adjustment=-1, is_realistic=True))
    assert out.severity == 9


def test_validator_may_lower_an_unrealistic_finding():
    out = apply_validation(_risk(10, 3, 3), _validation(severity_adjustment=-2, is_realistic=False))
    assert out.severity == 8 and out.priority == "Medium"


def test_guard_does_not_touch_other_severities_or_raises():
    v = _validation(is_realistic=True)
    assert guarded_severity(8, 6, v) == 6
    assert guarded_severity(9, 10, v) == 10
    assert guarded_severity(10, 9, v) == 9


def test_validator_adjustment_rederives_priority_and_reason():
    out = apply_validation(_risk(5, 5, 5), _validation(occurrence_adjustment=2, detection_adjustment=2))
    assert (out.rpn, out.priority) == (5 * 7 * 7, "High") and out.priority_reason == "High: RPN 245"


def test_confirmed_exploit_proxy_comes_from_validator_and_lifts_to_critical():
    v = _validation(is_realistic=True, attack_chain_complete=True, confidence=0.8)
    assert exploit_confirmed_from(v)
    assert apply_validation(_risk(10, 2, 6), v).priority == "Critical"
    assert not exploit_confirmed_from(_validation(confidence=0.69))
    assert not exploit_confirmed_from(_validation(attack_chain_complete=False, confidence=0.9))
    assert apply_validation(_risk(10, 2, 6), _validation(confidence=0.5)).priority == "High"
