"""
core/priority.py — the one place that turns S/O/D into a priority band (B-034, ADR-020).

RPN bands alone bury catastrophic failures (S10/O3/D3 = RPN 90 = Medium), so severity
floors are applied on top. Nothing else in the codebase may compute a band.
"""

from __future__ import annotations

from typing import NamedTuple

# ── Configuration table ───────────────────────────────────────────────────────
RPN_CRITICAL_ABOVE = 400
RPN_HIGH_ABOVE = 200
CATASTROPHIC_SEVERITY = 9          # S >= this is never below High; also the watchlist threshold
CRITICAL_SEVERITY = 10             # S == this, with a confirmed exploit and weak detection, is Critical
CRITICAL_MIN_DETECTION = 6
MIN_DOWNGRADE_JUSTIFICATION_CHARS = 15   # same bar as the chat proposals
CONFIRMED_MIN_CONFIDENCE = 0.7     # validator confidence that counts as "confirmed" until B-028 proves exploits

_RANK = {"Medium": 0, "High": 1, "Critical": 2}


class Priority(NamedTuple):
    band: str
    reason: str


def priority_for(severity: int, occurrence: int, detection: int, exploit_confirmed: bool = False) -> Priority:
    rpn = severity * occurrence * detection
    rpn_band = "Critical" if rpn > RPN_CRITICAL_ABOVE else "High" if rpn > RPN_HIGH_ABOVE else "Medium"
    band, reason = rpn_band, f"{rpn_band}: RPN {rpn}"
    if severity >= CATASTROPHIC_SEVERITY and _RANK[band] < _RANK["High"]:
        band, reason = "High", f"High: severity {severity} floor, RPN {rpn} alone would be {rpn_band}"
    if (severity >= CRITICAL_SEVERITY and exploit_confirmed
            and detection >= CRITICAL_MIN_DETECTION and _RANK[band] < _RANK["Critical"]):
        band = "Critical"
        reason = (f"Critical: severity {severity} with a confirmed exploit path and weak detection "
                  f"(D{detection}), RPN {rpn} alone would be {rpn_band}")
    return Priority(band, reason)


def lowers_catastrophic_severity(current: int, new: int) -> bool:
    """True when an adjustment takes a watchlist severity (>= 9) below 9."""
    return current >= CATASTROPHIC_SEVERITY and new < CATASTROPHIC_SEVERITY


def exploit_confirmed_from(validation) -> bool:
    """Proxy for a confirmed exploit path: the validator found it realistic, complete and confident."""
    return bool(validation.is_realistic and validation.attack_chain_complete
                and validation.confidence >= CONFIRMED_MIN_CONFIDENCE)


def guarded_severity(old: int, proposed: int, validation) -> int:
    """The validator may not take a catastrophic severity below 9 unless it judges the finding unrealistic."""
    if old >= CATASTROPHIC_SEVERITY and proposed < CATASTROPHIC_SEVERITY and validation.is_realistic:
        return CATASTROPHIC_SEVERITY
    return proposed
