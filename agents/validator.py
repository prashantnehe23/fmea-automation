"""
FMEA Validator: peer-reviews each failure mode and its RPN score.

Role: dual expert — Certified FMEA Practitioner + Business Risk Analyst.
The validator challenges whether S, O, D scores are correctly calibrated
against the true FMEA definitions (not just technical severity) and whether
the failure mode is realistic and exploitable in the stated business context.

Uses a single batched LLM call for all failures, with per-item fallback on error.
"""

from __future__ import annotations

import json

from core.llm import call_llm, extract_json_text
from core.models import FailureMode, RiskScore, ValidationResult

_ROLE_AND_DEFINITIONS = """
You are a dual expert:

1. A Certified FMEA Practitioner with 20 years of experience across financial services,
   SaaS platforms, and regulated industries. You calibrate S, O, D against real-world
   data and industry benchmarks — you catch over-scoring AND under-scoring equally.

2. A Business Risk Analyst who understands operational criticality at a business level.
   You know that a "minor" authentication flaw can enable lateral movement that brings
   down an entire infrastructure. You understand which business processes run daily vs
   monthly, and how that changes occurrence likelihood.

=== FMEA DEFINITIONS YOU APPLY ===

SEVERITY (1–10): Impact to business operations IF this failure occurs.
  Score in the context of the business the system supports — not just the component.
  ALSO consider indirect impact: credential exposure or auth bypass scores higher
  because it enables lateral movement into adjacent critical systems.
  1 = negligible. 10 = catastrophic, business-stopping, or regulatory/legal consequence.

OCCURRENCE (1–10): Probability the failure mode is triggered/exploited in practice.
  Penalise credential/auth failures higher — automated scanners probe continuously.
  For business-process-specific scenarios, consider execution frequency:
    Daily customer transactions → high (7–9). Weekly batch → moderate (5–6).
    Monthly payroll/payment → lower (3–5). Annual reconciliation → low (1–3).
  External customers (higher exposure) vs internal employees (lower).

DETECTION (1–10): How hard is it to detect BEFORE harm occurs? Higher = harder.
  PRE-HARM controls: SAST, testing, code review, runtime monitoring, alerting, SIEM.
  No logging + no alerting + silent failure → high detection score (8–10).
  Comprehensive monitoring + audit trail → low detection score (2–4).
"""


def _coerce_one(raw: object, failure_mode: str) -> ValidationResult:
    """Coerce a single LLM result dict into a ValidationResult; never raises."""
    if not isinstance(raw, dict):
        raw = {}

    def _bool(key: str, default: bool = True) -> bool:
        val = raw.get(key, default)
        if isinstance(val, bool):
            return val
        return str(val).lower() not in ("false", "no", "0")

    def _int_clamp(key: str, lo: int = -2, hi: int = 2) -> int:
        try:
            return max(lo, min(hi, int(raw.get(key, 0))))
        except (TypeError, ValueError):
            return 0

    def _float01(key: str) -> float:
        try:
            return max(0.0, min(1.0, float(raw.get(key, 0.5))))
        except (TypeError, ValueError):
            return 0.5

    challenges_raw = raw.get("challenges", [])
    if isinstance(challenges_raw, str):
        challenges = [challenges_raw]
    elif isinstance(challenges_raw, list):
        challenges = [str(c) for c in challenges_raw if str(c).strip()]
    else:
        challenges = []

    return ValidationResult(
        failure_mode=failure_mode,
        is_realistic=_bool("is_realistic"),
        attack_chain_complete=_bool("attack_chain_complete"),
        rpn_calibrated=_bool("rpn_calibrated"),
        challenges=challenges,
        severity_adjustment=_int_clamp("severity_adjustment"),
        occurrence_adjustment=_int_clamp("occurrence_adjustment"),
        detection_adjustment=_int_clamp("detection_adjustment"),
        confidence=_float01("confidence"),
        verdict=str(raw.get("verdict", "Validation completed."))[:400],
    )


def _build_batch_prompt(
    failures: list[FailureMode],
    risks: list[RiskScore],
) -> str:
    items = []
    for i, (f, r) in enumerate(zip(failures, risks)):
        items.append({
            "index": i,
            "failure_mode": f.failure_mode,
            "attack_chain": f.attack_chain,
            "business_impact": f.business_impact,
            "blast_radius": f.blast_radius,
            "trigger": f.trigger,
            "evidence": f.evidence or "none provided",
            "severity": r.severity,
            "severity_rationale": r.severity_rationale,
            "occurrence": r.occurrence,
            "occurrence_rationale": r.occurrence_rationale,
            "detection": r.detection,
            "detection_rationale": r.detection_rationale,
            "rpn": r.rpn,
            "priority": r.priority,
        })

    return f"""
{_ROLE_AND_DEFINITIONS}

=== CHALLENGE CRITERIA (apply to each entry) ===
1. Is the failure mode realistic and actually exploitable, or purely hypothetical?
2. Is the attack chain complete — are steps missing that would be required in practice?
3. Is Severity correctly calibrated? Has indirect impact (lateral movement) been considered?
4. Is Occurrence correctly calibrated? Does it reflect process frequency and actor type?
5. Is Detection correctly calibrated? Does it reflect what exists (or is missing) pre-harm?
6. Is the RPN priority (Critical/High/Medium) appropriate overall?

=== FAILURE MODES TO REVIEW ===
{json.dumps(items, indent=2)}

=== OUTPUT ===
Return a JSON array of {len(failures)} validation objects, in the SAME ORDER as the input.
Each object must have exactly these keys:
{{
  "failure_mode": "<exact failure_mode string from input>",
  "is_realistic": true/false,
  "attack_chain_complete": true/false,
  "rpn_calibrated": true/false,
  "challenges": ["<specific criticism 1>", "<specific criticism 2>", ...],
  "severity_adjustment": <integer -2 to +2>,
  "occurrence_adjustment": <integer -2 to +2>,
  "detection_adjustment": <integer -2 to +2>,
  "confidence": <float 0.0–1.0>,
  "verdict": "<one sentence overall assessment>"
}}

Adjustments: positive = increase, negative = decrease. Use 0 when correctly calibrated.
Only recommend non-zero adjustments when you have a concrete, articulable reason.
Return only the JSON array — no explanation outside the array.
"""


def run_validator(
    failures: list[FailureMode],
    risks: list[RiskScore],
) -> list[ValidationResult]:
    """
    Challenge all (failure, risk) pairs in a single batched LLM call.
    Falls back to individual calls per item if the batch response is malformed.
    Returns one ValidationResult per failure mode, in the same order.
    """
    try:
        prompt = _build_batch_prompt(failures, risks)
        response = call_llm(prompt, max_tokens=8000)
        raw_list = json.loads(extract_json_text(response))

        if not isinstance(raw_list, list):
            raw_list = [raw_list]

        # Index by failure_mode for robust ordering
        by_fm: dict[str, dict] = {}
        for item in raw_list:
            if isinstance(item, dict):
                key = str(item.get("failure_mode", "")).strip()
                if key:
                    by_fm[key] = item

        results: list[ValidationResult] = []
        for i, f in enumerate(failures):
            raw = by_fm.get(f.failure_mode) or (raw_list[i] if i < len(raw_list) else {})
            results.append(_coerce_one(raw, f.failure_mode))

        return results

    except Exception as batch_exc:
        # Batch failed — fall back to individual calls
        results = []
        for failure, risk in zip(failures, risks):
            single_prompt = f"""
{_ROLE_AND_DEFINITIONS}

=== FAILURE MODE UNDER REVIEW ===
Name: {failure.failure_mode}
Attack chain: {json.dumps(failure.attack_chain)}
Business impact: {failure.business_impact}
Blast radius: {failure.blast_radius}
Trigger: {failure.trigger}
Evidence: {failure.evidence or "none provided"}

=== RPN SCORE UNDER REVIEW ===
Severity: {risk.severity}/10 — {risk.severity_rationale}
Occurrence: {risk.occurrence}/10 — {risk.occurrence_rationale}
Detection: {risk.detection}/10 — {risk.detection_rationale}
RPN: {risk.rpn} → Priority: {risk.priority}

Return JSON only:
{{
  "failure_mode": "{failure.failure_mode}",
  "is_realistic": true/false,
  "attack_chain_complete": true/false,
  "rpn_calibrated": true/false,
  "challenges": ["..."],
  "severity_adjustment": <-2 to +2>,
  "occurrence_adjustment": <-2 to +2>,
  "detection_adjustment": <-2 to +2>,
  "confidence": <0.0–1.0>,
  "verdict": "<one sentence>"
}}
"""
            try:
                resp = call_llm(single_prompt, max_tokens=1500)
                raw = json.loads(extract_json_text(resp))
                results.append(_coerce_one(raw, failure.failure_mode))
            except Exception as exc:
                results.append(
                    ValidationResult(
                        failure_mode=failure.failure_mode,
                        is_realistic=True,
                        attack_chain_complete=True,
                        rpn_calibrated=True,
                        challenges=[f"Validator error (batch: {batch_exc}; single: {exc})"],
                        confidence=0.0,
                        verdict="Validation could not be completed due to an error.",
                    )
                )
        return results
