"""
FMEA Actuary: scores Severity, Occurrence, and Detection via LLM reasoning.

FMEA definitions applied:
- Severity (1–10): Business impact IF the failure occurs. Considers operational
  criticality of the system AND vulnerability type (e.g. credential exposure
  enables lateral movement even on a non-critical system).
- Occurrence (1–10): Probability the failure mode is triggered in practice.
  Considers business process frequency (daily/weekly/monthly), who executes
  it (customers vs employees), and inherent exploitability.
- Detection (1–10): How hard it is to detect BEFORE harm occurs. Higher = harder.
  Considers pre-production controls (SAST, testing) and runtime controls
  (monitoring, alerting, SIEM, audit trails).
"""

import json

from core.llm import call_llm, extract_json_text
from core.models import ControlAssessment, FailureMode, RiskScore, SystemContext
from core.untrusted import as_data_block

_SCORING_DEFINITIONS = """
SEVERITY (1–10) — Impact to business operations IF this failure occurs.
- Score relative to the business this system supports. 1 = negligible. 10 = catastrophic.
- Use tiering data: Tier 1 = mission-critical; Tier 2 = important; Tier 3 = supporting.
- Consider BOTH direct impact AND indirect: credential/auth-bypass on any system scores
  higher because it grants a foothold for lateral movement into adjacent critical systems.
- Vulnerability types enabling environment entry (auth bypass, secrets exposure,
  privilege escalation) warrant severity ≥ 7 regardless of the host component's tier.

OCCURRENCE (1–10) — Probability the failure mode is triggered/exploited in practice.
- Penalise exposed credentials and auth flaws higher: automated scanners probe continuously.
- For business-process-specific failures, consider execution frequency:
    Daily customer transactions → 7–9.  Weekly batch jobs → 5–6.
    Monthly payroll/payment runs → 3–5.  Annual reconciliation → 1–3.
  Also: external customers (higher exposure) vs internal employees (lower).
- Generic infrastructure weaknesses (race conditions, injection, bypass) → higher,
  because any request can trigger them.

DETECTION (1–10) — How hard is it to detect this failure BEFORE it causes harm?
- Higher = harder to detect (worse). Lower = easier (better).
- Focus on PRE-HARM controls: tests, SAST, code review, anomaly detection,
  runtime alerting, SIEM, audit trails.
- "No logging / no visibility / silent failure / blind spot / no alerting" → push up.
- Comprehensive monitoring + alerting + audit trail → reduce score.
- Race conditions and timing attacks are inherently hard to observe → push up.
"""


def _build_batch_prompt(
    failures: list[FailureMode],
    controls: list[ControlAssessment],
    context: SystemContext,
) -> str:
    items = []
    for i, (f, c) in enumerate(zip(failures, controls)):
        items.append({
            "index": i,
            "failure_mode": f.failure_mode,
            "attack_chain": f.attack_chain,
            "business_impact": f.business_impact,
            "blast_radius": f.blast_radius,
            "trigger": f.trigger,
            "evidence": f.evidence or "",
            "controls": c.controls,
            "control_maturity": c.control_maturity,
            "gaps": c.gaps,
        })

    return f"""
You are an FMEA actuary. Score all failure modes below using rigorous FMEA methodology.

=== BUSINESS CONTEXT ===
System tiering (component → criticality):
{json.dumps(context.tiering, indent=2)}

Attack surfaces:
{json.dumps(context.attack_surfaces, indent=2)}

Failure domains:
{json.dumps(context.failure_domains, indent=2)}

=== SCORING DEFINITIONS ===
{_SCORING_DEFINITIONS}

=== FAILURE MODES TO SCORE ===
{json.dumps(items, indent=2)}

=== OUTPUT ===
Return a JSON array of {len(failures)} score objects, in the SAME ORDER as the input.
Each object must have exactly these keys:
{{
  "failure_mode": "<exact failure_mode string from input>",
  "severity": <int 1–10>,
  "severity_rationale": "<one sentence: business impact and why, referencing tier or vulnerability type>",
  "occurrence": <int 1–10>,
  "occurrence_rationale": "<one sentence: process frequency, actor type, or exploitability>",
  "detection": <int 1–10>,
  "detection_rationale": "<one sentence: what detection mechanism exists or is missing>"
}}

Return only the JSON array — no explanation outside the array.
"""


def _clamp(val: object, lo: int = 1, hi: int = 10) -> int:
    try:
        return max(lo, min(hi, int(val)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 5


def _build_risk_score(
    raw: dict,
    failure: FailureMode,
    control: ControlAssessment,
) -> RiskScore:
    severity = _clamp(raw.get("severity", 5))
    occurrence = _clamp(raw.get("occurrence", 5))
    detection = _clamp(raw.get("detection", 5))

    se_rat = str(raw.get("severity_rationale", ""))[:220]
    oc_rat = str(raw.get("occurrence_rationale", ""))[:220]
    de_rat = str(raw.get("detection_rationale", ""))[:220]

    rpn = severity * occurrence * detection
    priority = "Critical" if rpn > 400 else "High" if rpn > 200 else "Medium"

    trig = (failure.trigger or "").strip()
    trig_bit = f" ({trig[:60]}…)" if len(trig) > 60 else (f" ({trig})" if trig else "")
    gist = (failure.failure_mode or "This scenario").strip()
    if len(gist) > 100:
        gist = gist[:97] + "…"
    justification = (
        f"{gist}{trig_bit} maps to {priority} BCP-style risk (RPN {rpn}) given "
        f"{control.control_maturity} control maturity and listed gaps."
    )
    if len(justification) > 320:
        justification = justification[:317] + "…"

    return RiskScore(
        failure_mode=failure.failure_mode,
        severity=severity,
        occurrence=occurrence,
        detection=detection,
        rpn=rpn,
        priority=priority,
        justification=justification,
        severity_rationale=se_rat,
        occurrence_rationale=oc_rat,
        detection_rationale=de_rat,
    )


def _risk_score_from_locked(row: dict, failure: FailureMode) -> RiskScore:
    """Reconstruct a RiskScore from a locked scenario registry row."""
    s = int(row.get("severity", 5))
    o = int(row.get("occurrence", 5))
    d = int(row.get("detection", 5))
    rpn = s * o * d
    priority = "Critical" if rpn > 400 else "High" if rpn > 200 else "Medium"
    return RiskScore(
        failure_mode=failure.failure_mode,
        severity=s,
        occurrence=o,
        detection=d,
        rpn=rpn,
        priority=priority,
        justification=f"Locked scenario — scores carried over from first scan (RPN {rpn}).",
        severity_rationale="Carried over from first scan.",
        occurrence_rationale="Carried over from first scan.",
        detection_rationale="Carried over from first scan.",
    )


def score_all_failures(
    failures: list[FailureMode],
    controls: list[ControlAssessment],
    context: SystemContext,
    business_context: str = "",
    locked_rpn: dict[str, dict] | None = None,
) -> list[RiskScore]:
    """
    Score all failures.  For scenarios present in locked_rpn (exact name match),
    the stored scores are returned directly — no LLM call.  Only genuinely new
    scenarios are sent to the LLM in a single batched call.
    """
    locked_rpn = locked_rpn or {}

    # Partition into locked (skip LLM) and new (need scoring)
    locked_results: dict[int, RiskScore] = {}
    new_failures: list[FailureMode] = []
    new_controls: list[ControlAssessment] = []
    new_indices: list[int] = []

    for i, (f, c) in enumerate(zip(failures, controls)):
        if f.failure_mode in locked_rpn:
            locked_results[i] = _risk_score_from_locked(locked_rpn[f.failure_mode], f)
        else:
            new_failures.append(f)
            new_controls.append(c)
            new_indices.append(i)

    # Score only new scenarios (single batched LLM call)
    new_scored: list[RiskScore] = []
    if new_failures:
        prompt = _build_batch_prompt(new_failures, new_controls, context)
        if as_data_block("business_context", business_context):
            prompt = (
                "Business context for severity calibration:\n"
                + as_data_block("business_context", business_context) + "\n\n" + prompt
            )
        response = call_llm(prompt, max_tokens=6000)
        raw_list = json.loads(extract_json_text(response))
        if not isinstance(raw_list, list):
            raw_list = [raw_list]

        by_fm: dict[str, dict] = {}
        for item in raw_list:
            if isinstance(item, dict):
                key = str(item.get("failure_mode", "")).strip()
                if key:
                    by_fm[key] = item

        for j, (f, c) in enumerate(zip(new_failures, new_controls)):
            raw = by_fm.get(f.failure_mode) or (raw_list[j] if j < len(raw_list) else {})
            new_scored.append(_build_risk_score(raw, f, c))

    # Merge results back in original order
    results: list[RiskScore] = [None] * len(failures)  # type: ignore[list-item]
    for i, score in locked_results.items():
        results[i] = score
    for j, i in enumerate(new_indices):
        results[i] = new_scored[j]

    return results


def score_failure(
    failure: FailureMode,
    control: ControlAssessment,
    context: SystemContext,
) -> RiskScore:
    """Score a single failure mode. Use score_all_failures for batch efficiency."""
    return score_all_failures([failure], [control], context)[0]
