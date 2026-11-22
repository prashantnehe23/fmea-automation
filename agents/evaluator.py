"""
FMEA Pipeline Evaluator — rule-based, zero LLM calls.

Checks three dimensions for each agent in the pipeline:
  1. Task success   — did the agent produce the correct output for its role?
  2. Reasoning quality — are reasoning indicators (chain/tree/role artifacts) present?
  3. Cost           — reports call count and estimates USD cost for the run.

All checks are deterministic and execute in microseconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.models import (
    ControlAssessment,
    FailureMode,
    RemediationPlan,
    RiskScore,
    SystemContext,
    ValidationResult,
)
from core.priority import priority_for

# Rough per-call token estimates (input, output) for each agent type after batching
_CALL_TOKEN_ESTIMATES: dict[str, tuple[int, int]] = {
    "surveyor":          (3_000,    800),
    "saboteur":          (5_000,  3_000),
    "controls_assessor": (6_000,  2_500),   # batched
    "actuary":           (8_000,  2_000),   # batched
    "sre_agent":         (2_500,  1_500),   # per-failure (×N)
    "validator":         (8_000,  3_000),   # batched
    "scenario_linkage":  (4_000,  2_000),
}

_VALID_TIERS = {"tier 1", "tier 2", "tier 3"}
_VALID_MATURITIES = {"low", "moderate", "high"}

# Vulnerability categories the saboteur should cover for good breadth
_ATTACK_CATEGORIES = {
    "concurrency": ("race", "concurr", "timing", "toctou", "parallel", "double"),
    "injection":   ("inject", "sql", "xss", "command", "payload", "fuzz"),
    "secrets":     ("secret", "key", "credential", "hardcoded", "token", "password"),
    "auth_bypass": ("auth", "bypass", "privilege", "escalat", "unauthor", "session"),
    "input_valid": ("valid", "input", "negative", "zero", "overflow", "boundary"),
}


# ── Result types ────────────────────────────────────────────────────────────────

@dataclass
class AgentEval:
    agent: str
    passed: bool
    score: float            # 0.0–1.0
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PipelineEval:
    overall_passed: bool
    agents: list[AgentEval]
    llm_calls: int
    estimated_cost_usd: float
    scenario_count: int
    summary: str


# ── Individual agent checks ──────────────────────────────────────────────────────

def _eval_surveyor(context: SystemContext) -> AgentEval:
    issues: list[str] = []
    warnings: list[str] = []

    # Task success
    if not context.tiering:
        issues.append("No tiering produced — surveyor failed to map system components.")
    else:
        bad_tiers = [
            f"{k}={v}" for k, v in context.tiering.items()
            if v.strip().lower() not in _VALID_TIERS
        ]
        if bad_tiers:
            warnings.append(f"Non-standard tier values (expected Tier 1/2/3): {bad_tiers[:3]}")

    if not context.attack_surfaces:
        issues.append("No attack surfaces identified.")
    elif len(context.attack_surfaces) < 2:
        warnings.append("Only 1 attack surface — surveyor may have under-explored entry points.")

    if not context.failure_domains:
        issues.append("No failure domains identified.")

    # Reasoning quality (ToT indicator): tier diversity shows all 3 perspectives were used
    tier_values = set(v.strip().lower() for v in context.tiering.values())
    if len(tier_values) < 2 and len(context.tiering) > 2:
        warnings.append(
            "All components assigned the same tier — Tree of Thoughts synthesis may be shallow."
        )

    score = max(0.0, 1.0 - (len(issues) * 0.3 + len(warnings) * 0.1))
    return AgentEval("surveyor", passed=len(issues) == 0, score=round(score, 2),
                     issues=issues, warnings=warnings)


def _eval_saboteur(failures: list[FailureMode]) -> AgentEval:
    issues: list[str] = []
    warnings: list[str] = []

    if not failures:
        issues.append("No failure scenarios produced.")
        return AgentEval("saboteur", passed=False, score=0.0, issues=issues)

    # Task success: required fields + attack chain depth
    for i, f in enumerate(failures):
        label = f"Scenario {i+1} ({f.failure_mode[:40]})"
        if not f.failure_mode or f.failure_mode == "Unspecified failure":
            issues.append(f"{label}: missing failure_mode.")
        if not f.business_impact or f.business_impact == "Not specified":
            issues.append(f"{label}: missing business_impact.")
        if not f.trigger or f.trigger == "Not specified":
            issues.append(f"{label}: missing trigger.")
        if len(f.attack_chain) < 2:
            issues.append(f"{label}: attack_chain has fewer than 2 steps.")
        elif len(f.attack_chain) < 3:
            warnings.append(f"{label}: attack_chain has only {len(f.attack_chain)} steps — CoT should produce ≥3.")

    # Reasoning quality (CoT indicator): average chain length
    avg_chain = sum(len(f.attack_chain) for f in failures) / len(failures)
    if avg_chain < 3:
        warnings.append(
            f"Average attack chain length is {avg_chain:.1f} — "
            "chain-of-thought reasoning should yield more detailed step sequences."
        )

    # Coverage across vulnerability categories
    all_text = " ".join(
        f.failure_mode.lower() + " " + " ".join(f.attack_chain).lower()
        for f in failures
    )
    covered = {cat for cat, kws in _ATTACK_CATEGORIES.items() if any(k in all_text for k in kws)}
    if len(covered) < 2:
        warnings.append(
            f"Only {len(covered)} attack category covered ({covered or 'none'}) — "
            "consider expanding attack vector diversity."
        )

    score = max(0.0, 1.0 - (len(issues) * 0.25 + len(warnings) * 0.08))
    return AgentEval("saboteur", passed=len(issues) == 0, score=round(score, 2),
                     issues=issues, warnings=warnings)


def _eval_controls_assessor(
    controls: list[ControlAssessment],
    failures: list[FailureMode],
) -> AgentEval:
    issues: list[str] = []
    warnings: list[str] = []

    if len(controls) != len(failures):
        issues.append(
            f"Expected {len(failures)} control assessments, got {len(controls)}."
        )

    for i, c in enumerate(controls):
        label = f"Control {i+1} ({c.failure_mode[:40]})"
        if c.control_maturity not in _VALID_MATURITIES:
            issues.append(f"{label}: invalid control_maturity '{c.control_maturity}'.")
        if not c.controls:
            warnings.append(f"{label}: no controls listed — may indicate an empty assessment.")
        if not c.gaps:
            warnings.append(f"{label}: no gaps listed.")
        elif len(c.gaps) == 1 and "unverified" in c.gaps[0].lower():
            warnings.append(f"{label}: gaps contain only the default fallback string.")

    score = max(0.0, 1.0 - (len(issues) * 0.3 + len(warnings) * 0.1))
    return AgentEval("controls_assessor", passed=len(issues) == 0, score=round(score, 2),
                     issues=issues, warnings=warnings)


def _eval_actuary(
    risks: list[RiskScore],
    failures: list[FailureMode],
) -> AgentEval:
    issues: list[str] = []
    warnings: list[str] = []

    if len(risks) != len(failures):
        issues.append(f"Expected {len(failures)} risk scores, got {len(risks)}.")

    for r in risks:
        label = f"RPN ({r.failure_mode[:40]})"

        # Arithmetic check: RPN must equal S × O × D
        expected_rpn = r.severity * r.occurrence * r.detection
        if r.rpn != expected_rpn:
            issues.append(
                f"{label}: RPN {r.rpn} ≠ S{r.severity}×O{r.occurrence}×D{r.detection}={expected_rpn}."
            )

        # Range checks
        for name, val in [("severity", r.severity), ("occurrence", r.occurrence),
                          ("detection", r.detection)]:
            if not (1 <= val <= 10):
                issues.append(f"{label}: {name}={val} out of range 1–10.")

        # Priority consistency
        # Either answer is valid: whether an exploit was confirmed is decided later, by the validator.
        allowed = {priority_for(r.severity, r.occurrence, r.detection, confirmed).band
                   for confirmed in (False, True)}
        if r.priority not in allowed:
            issues.append(
                f"{label}: priority='{r.priority}' inconsistent with S{r.severity}/O{r.occurrence}/"
                f"D{r.detection} (expected one of {sorted(allowed)})."
            )

        # Reasoning quality: rationales must be substantive
        for name, rat in [("severity", r.severity_rationale), ("occurrence", r.occurrence_rationale),
                          ("detection", r.detection_rationale)]:
            if len(rat.strip()) < 20:
                warnings.append(f"{label}: {name}_rationale is too short — may lack business context.")

    score = max(0.0, 1.0 - (len(issues) * 0.3 + len(warnings) * 0.08))
    return AgentEval("actuary", passed=len(issues) == 0, score=round(score, 2),
                     issues=issues, warnings=warnings)


def _eval_validator(
    validations: list[ValidationResult],
    failures: list[FailureMode],
) -> AgentEval:
    issues: list[str] = []
    warnings: list[str] = []

    if len(validations) != len(failures):
        issues.append(f"Expected {len(failures)} validations, got {len(validations)}.")

    for v in validations:
        label = f"Validation ({v.failure_mode[:40]})"

        if not v.verdict or v.verdict in ("Validation completed.", ""):
            warnings.append(f"{label}: verdict is empty or default — review may be superficial.")

        if not v.challenges:
            warnings.append(f"{label}: no challenges raised — validator may have rubber-stamped.")
        else:
            short = [c for c in v.challenges if len(c.strip()) < 30]
            if short:
                warnings.append(
                    f"{label}: {len(short)} challenge(s) are very short — "
                    "may lack specificity (role-based expert should give detailed criticism)."
                )

        if v.confidence == 0.5:
            warnings.append(f"{label}: confidence is default 0.5 — likely not set by the model.")

        for name, adj in [("severity", v.severity_adjustment),
                          ("occurrence", v.occurrence_adjustment),
                          ("detection", v.detection_adjustment)]:
            if not (-2 <= adj <= 2):
                issues.append(f"{label}: {name}_adjustment={adj} out of range -2 to +2.")

        if "error" in v.verdict.lower():
            issues.append(f"{label}: validator reported an error.")

    score = max(0.0, 1.0 - (len(issues) * 0.3 + len(warnings) * 0.08))
    return AgentEval("validator", passed=len(issues) == 0, score=round(score, 2),
                     issues=issues, warnings=warnings)


def _eval_sre(
    remediations: list[RemediationPlan],
    failures: list[FailureMode],
) -> AgentEval:
    issues: list[str] = []
    warnings: list[str] = []

    if len(remediations) != len(failures):
        issues.append(f"Expected {len(failures)} remediation plans, got {len(remediations)}.")

    for r in remediations:
        label = f"SRE ({r.failure_mode[:40]})"
        if not r.corrective and not r.preventive:
            if not (r.fixes or r.monitoring or r.resilience_upgrades):
                issues.append(f"{label}: no corrective or preventive actions were produced.")
            continue                                         # a plan stored before B-030: nothing structured to check

        if not any(a.verification for a in r.corrective):
            issues.append(f"{label}: no corrective action with a verification step.")
        if not r.preventive:
            issues.append(f"{label}: no preventive action.")
        for a in r.corrective + r.preventive:
            if not a.target:
                issues.append(f"{label}: action '{a.id}' has no target.")

    score = max(0.0, 1.0 - (len(issues) * 0.25 + len(warnings) * 0.08))
    return AgentEval("sre_agent", passed=len(issues) == 0, score=round(score, 2),
                     issues=issues, warnings=warnings)


# ── Cost estimation ──────────────────────────────────────────────────────────────

def _estimate_cost(llm_calls: int, scenario_count: int) -> float:
    """
    Rough USD cost estimate based on known call structure after batching.
    Priced at the active model's rates (core/costs.py). Actual cost depends on prompt/code size.
    """
    total_input = total_output = 0

    # Fixed single calls
    for agent in ("surveyor", "saboteur", "controls_assessor", "actuary",
                  "validator", "scenario_linkage"):
        inp, out = _CALL_TOKEN_ESTIMATES[agent]
        total_input += inp
        total_output += out

    # Per-failure calls (SRE)
    inp, out = _CALL_TOKEN_ESTIMATES["sre_agent"]
    total_input += inp * scenario_count
    total_output += out * scenario_count

    from core.costs import compute_cost
    from core.llm import get_model_name
    return round(compute_cost(get_model_name(), total_input, total_output), 4)


# ── Public API ───────────────────────────────────────────────────────────────────

def evaluate_pipeline(
    context: SystemContext,
    failures: list[FailureMode],
    controls: list[ControlAssessment],
    risks: list[RiskScore],
    remediations: list[RemediationPlan],
    validations: list[ValidationResult],
    llm_calls: int,
) -> PipelineEval:
    """
    Run all agent evaluations and return a PipelineEval report.
    No LLM calls are made — all checks are deterministic.
    """
    evals = [
        _eval_surveyor(context),
        _eval_saboteur(failures),
        _eval_controls_assessor(controls, failures),
        _eval_actuary(risks, failures),
        _eval_validator(validations, failures),
        _eval_sre(remediations, failures),
    ]

    all_passed = all(e.passed for e in evals)
    total_issues = sum(len(e.issues) for e in evals)
    total_warnings = sum(len(e.warnings) for e in evals)
    avg_score = round(sum(e.score for e in evals) / len(evals), 2)
    cost = _estimate_cost(llm_calls, len(failures))

    failed_agents = [e.agent for e in evals if not e.passed]
    if all_passed and total_warnings == 0:
        summary = (
            f"All {len(evals)} agents passed with no issues. "
            f"Avg quality score {avg_score}/1.0. "
            f"{llm_calls} LLM calls, ~${cost} estimated."
        )
    elif all_passed:
        summary = (
            f"All agents passed ({total_warnings} warning(s)). "
            f"Avg quality score {avg_score}/1.0. "
            f"{llm_calls} LLM calls, ~${cost} estimated."
        )
    else:
        summary = (
            f"{len(failed_agents)} agent(s) failed: {failed_agents}. "
            f"{total_issues} issue(s), {total_warnings} warning(s). "
            f"Avg quality score {avg_score}/1.0. "
            f"{llm_calls} LLM calls, ~${cost} estimated."
        )

    return PipelineEval(
        overall_passed=all_passed,
        agents=evals,
        llm_calls=llm_calls,
        estimated_cost_usd=cost,
        scenario_count=len(failures),
        summary=summary,
    )
