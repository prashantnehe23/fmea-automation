"""
LLM-as-judge: enriches the rule-based evaluator with qualitative scores.

A single batched LLM call judges four agents:
  - saboteur:   attack chain depth and realism
  - actuary:    RPN calibration quality
  - validator:  challenge specificity
  - sre_agent:  remediation plan actionability

Returns one JudgeVerdict per judged agent.
Falls back gracefully (empty verdicts) if the LLM call fails.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from core.actions import plan_actions
from core.llm import call_llm, extract_json_text
from core.models import FailureMode, RemediationPlan, RiskScore, ValidationResult

_JUDGED_AGENTS = ("saboteur", "actuary", "validator", "sre_agent")


@dataclass
class JudgeVerdict:
    agent: str
    reasoning_quality: float    # 0–1  (depth, coherence)
    specificity: float          # 0–1  (concrete detail vs generic)
    calibration: float          # 0–1  (correctness / consistency)
    overall: float              # weighted mean of the three
    commentary: str             # one sentence


def _empty_verdict(agent: str) -> JudgeVerdict:
    return JudgeVerdict(
        agent=agent,
        reasoning_quality=0.0,
        specificity=0.0,
        calibration=0.0,
        overall=0.0,
        commentary="Judge could not evaluate this agent.",
    )


def _coerce(raw: dict, agent: str) -> JudgeVerdict:
    def _f(key: str) -> float:
        try:
            return max(0.0, min(1.0, float(raw.get(key, 0.5))))
        except (TypeError, ValueError):
            return 0.5

    rq = _f("reasoning_quality")
    sp = _f("specificity")
    ca = _f("calibration")
    overall = round((rq * 0.35 + sp * 0.35 + ca * 0.30), 3)
    commentary = str(raw.get("commentary", ""))[:300] or "No commentary provided."
    return JudgeVerdict(
        agent=agent,
        reasoning_quality=round(rq, 3),
        specificity=round(sp, 3),
        calibration=round(ca, 3),
        overall=overall,
        commentary=commentary,
    )


def _build_prompt(
    failures: list[FailureMode],
    risks: list[RiskScore],
    validations: list[ValidationResult],
    remediations: list[RemediationPlan],
) -> str:
    # Build concise summaries to keep the prompt lean
    saboteur_sample = [
        {
            "failure_mode": f.failure_mode,
            "chain_length": len(f.attack_chain),
            "chain_preview": f.attack_chain[:3],
            "has_trigger": bool(f.trigger and f.trigger != "Not specified"),
            "has_business_impact": bool(f.business_impact and f.business_impact != "Not specified"),
        }
        for f in failures[:5]
    ]

    actuary_sample = [
        {
            "failure_mode": r.failure_mode,
            "S": r.severity, "O": r.occurrence, "D": r.detection, "RPN": r.rpn,
            "severity_rationale": r.severity_rationale[:120],
            "occurrence_rationale": r.occurrence_rationale[:120],
            "detection_rationale": r.detection_rationale[:120],
        }
        for r in risks[:5]
    ]

    validator_sample = [
        {
            "failure_mode": v.failure_mode,
            "challenges": v.challenges[:3],
            "verdict": v.verdict[:120],
            "adjustments": {
                "S": v.severity_adjustment,
                "O": v.occurrence_adjustment,
                "D": v.detection_adjustment,
            },
            "confidence": v.confidence,
        }
        for v in validations[:5]
    ]

    sre_sample = [
        {
            "failure_mode": r.failure_mode,
            "corrective_count": len(corrective),
            "corrective_preview": [a.title for a in corrective[:2]],
            "corrective_with_verification": sum(1 for a in corrective if a.verification),
            "preventive_count": len(preventive),
            "preventive_kinds": sorted({a.kind for a in preventive}),
        }
        for r in remediations[:5]
        for corrective, preventive in [plan_actions(r)]
    ]

    return f"""
You are an expert FMEA quality judge. Score the four pipeline agents below.

For each agent return scores 0.0–1.0:
- reasoning_quality: depth and coherence of reasoning (chain length, rationale completeness)
- specificity: concrete, code-specific detail vs generic boilerplate
- calibration: correctness and consistency (RPN arithmetic, realistic scores, actionable plans)

=== SABOTEUR OUTPUT (failure mode generation) ===
{json.dumps(saboteur_sample, indent=2)}

=== ACTUARY OUTPUT (RPN scoring) ===
{json.dumps(actuary_sample, indent=2)}

=== VALIDATOR OUTPUT (peer review) ===
{json.dumps(validator_sample, indent=2)}

=== SRE AGENT OUTPUT (remediation plans) ===
{json.dumps(sre_sample, indent=2)}

Return a JSON array of exactly 4 objects in this order: saboteur, actuary, validator, sre_agent.
Each object:
{{
  "agent": "<saboteur|actuary|validator|sre_agent>",
  "reasoning_quality": <0.0–1.0>,
  "specificity": <0.0–1.0>,
  "calibration": <0.0–1.0>,
  "commentary": "<one sentence assessment>"
}}
Return only the JSON array.
""".strip()


def run_llm_judge(
    failures: list[FailureMode],
    risks: list[RiskScore],
    validations: list[ValidationResult],
    remediations: list[RemediationPlan],
) -> list[JudgeVerdict]:
    """
    Run the LLM judge in a single batched call.
    Returns one JudgeVerdict per judged agent, in the order:
    saboteur, actuary, validator, sre_agent.
    Falls back to empty verdicts if the call fails.
    """
    if not failures or not risks:
        return [_empty_verdict(a) for a in _JUDGED_AGENTS]

    try:
        prompt = _build_prompt(failures, risks, validations, remediations)
        response = call_llm(prompt, max_tokens=2000)
        raw_list = json.loads(extract_json_text(response))
        if not isinstance(raw_list, list):
            raw_list = [raw_list]

        by_agent: dict[str, dict] = {}
        for item in raw_list:
            if isinstance(item, dict):
                key = str(item.get("agent", "")).strip()
                if key:
                    by_agent[key] = item

        return [
            _coerce(by_agent[agent], agent) if agent in by_agent else _empty_verdict(agent)
            for agent in _JUDGED_AGENTS
        ]

    except Exception:
        return [_empty_verdict(a) for a in _JUDGED_AGENTS]
