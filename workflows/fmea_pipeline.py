from __future__ import annotations

from agents.actuary import score_all_failures
from agents.controls_assessor import run_controls_assessor
from agents.evaluator import evaluate_pipeline
from agents.llm_judge import run_llm_judge
from agents.saboteur import run_saboteur
from agents.scenario_linkage import run_scenario_linkage
from agents.sre_agent import run_sre_agent
from agents.surveyor import run_surveyor
from agents.validator import run_validator
from core.line_numbers import number_lines
from core.llm import get_call_count, reset_call_count
from core.priority import exploit_confirmed_from, guarded_severity, priority_for
from core.telemetry import agent_span, clear_scan_context, get_run_id, set_scan_context
from memory import eval_store, workspace_store
import memory.db as _db
from memory.scenario_registry import (
    clear_registry,
    find_matching_scenario,
    get_locked_scenarios,
    register_new_scenarios,
    scenario_count,
)

def apply_validation(risk, validation):
    """Apply the validator's score adjustments to an unlocked risk and re-derive its priority."""
    adj_s = guarded_severity(
        risk.severity, max(1, min(10, risk.severity + validation.severity_adjustment)), validation)
    adj_o = max(1, min(10, risk.occurrence + validation.occurrence_adjustment))
    adj_d = max(1, min(10, risk.detection + validation.detection_adjustment))
    priority, reason = priority_for(adj_s, adj_o, adj_d, exploit_confirmed_from(validation))
    return risk.model_copy(update={
        "severity": adj_s, "occurrence": adj_o, "detection": adj_d,
        "rpn": adj_s * adj_o * adj_d, "priority": priority, "priority_reason": reason,
    })


# Demo / predictable billing: at most this many failure modes (2 + 2*N API calls).
DEFAULT_MAX_FAILURE_MODES = 7


def run_fmea(
    code: str,
    *,
    max_failure_modes: int = DEFAULT_MAX_FAILURE_MODES,
    force_rerun: bool = False,
    workspace=None,
    on_progress=None,
) -> dict:
    """
    Run the full FMEA pipeline with caching, learning, validation, and evaluation.

    workspace: optional WorkspaceContext — scopes cache, learning, and eval history
               per customer/project.  Pass None to use global (legacy) paths.

    Call structure (after batching):
      surveyor(1) + saboteur(1) + linkage(1) + controls(1) + actuary(1)
      + sre(N) + validator(1) + llm_judge(1) = 7 + N calls total.

    On cache hit: LLM calls skipped; cached result returned instantly.
    """
    from memory.workspace_store import (
        cache_result,
        get_cached_result,
        get_learning_context,
        get_memory_stats,
        update_from_run,
    )

    # ── Cache check ────────────────────────────────────────────────────────────
    if not force_rerun:
        cached = get_cached_result(code, workspace)
        if cached is not None:
            cached["memory_stats"] = get_memory_stats(workspace)
            return cached

    # ── Reset call counter for this run ───────────────────────────────────────
    reset_call_count()

    # ── Business context from workspace ───────────────────────────────────────
    biz_ctx = workspace.business_context if workspace else ""

    # ── DB workspace identity ─────────────────────────────────────────────────
    workspace_id: int | None = None
    if workspace is not None:
        workspace_id = _db.upsert_workspace(workspace)

    # ── Scenario registry: load locked scenarios for this workspace ───────────
    locked: list[dict] = get_locked_scenarios(workspace_id) if workspace_id else []
    locked_names: list[str] = [row["failure_mode"] for row in locked]
    locked_rpn: dict[str, dict] = {row["failure_mode"]: row for row in locked}

    # ── Learning context injection ─────────────────────────────────────────────
    learning_ctx = get_learning_context(workspace)

    # ── Set telemetry context (scan_id not yet known; workspace_id is enough) ──
    set_scan_context(scan_id=None, workspace_id=workspace_id)

    # ── Core pipeline ──────────────────────────────────────────────────────────
    # Agents see numbered lines so the line numbers they cite are real (B-041); the original
    # text is what is cached, fingerprinted and stored.
    prompt_code = number_lines(code)
    if on_progress: on_progress("surveyor")
    with agent_span("surveyor"):
        context = run_surveyor(prompt_code, business_context=biz_ctx)

    if on_progress: on_progress("saboteur")
    with agent_span("saboteur"):
        failures = run_saboteur(
            prompt_code, context,
            max_scenarios=max_failure_modes,
            learning_context=learning_ctx,
            locked_names=locked_names if locked_names else None,
        )
    failures = failures[:max_failure_modes]

    if on_progress: on_progress("controls")
    with agent_span("controls"):
        scenario_linkage = run_scenario_linkage(failures, prompt_code)
        controls = run_controls_assessor(failures, prompt_code)

    # Single batched actuary call — locked scenarios short-circuit (no LLM call)
    if on_progress: on_progress("actuary")
    with agent_span("actuary"):
        risks = score_all_failures(
            failures, controls, context,
            business_context=biz_ctx,
            locked_rpn=locked_rpn if locked_rpn else None,
        )

    # Per-failure SRE (complex plans benefit from focused attention)
    if on_progress: on_progress("sre")
    with agent_span("sre"):
        remediations = [run_sre_agent(f, c, r) for f, c, r in zip(failures, controls, risks)]

    # ── Validator (single batched call) ────────────────────────────────────────
    if on_progress: on_progress("validator")
    with agent_span("validator"):
        validations = run_validator(failures, risks)

    # Apply validated score adjustments — locked scenarios are exempt.
    # The validator is an LLM agent and is non-deterministic; applying its
    # adjustments on top of a locked score would break RPN determinism on rescan.
    # Locked scenarios were already validated on their first run; skip them here.
    for i, (risk, validation) in enumerate(zip(risks, validations)):
        if failures[i].failure_mode in locked_rpn:
            continue  # score is locked — validator cannot override it
        risks[i] = apply_validation(risk, validation)

    # ── Semantic deduplication: fix any LLM renames despite constraint ────────
    if locked and workspace_id:
        for i, (f, r) in enumerate(zip(failures, risks)):
            if f.failure_mode not in locked_rpn:
                match = find_matching_scenario(f.failure_mode, list(f.attack_chain), locked)
                if match:
                    canonical = match["failure_mode"]
                    failures[i] = f.model_copy(update={"failure_mode": canonical})
                    m_s, m_o, m_d = match["severity"], match["occurrence"], match["detection"]
                    priority, reason = priority_for(m_s, m_o, m_d)
                    risks[i] = r.model_copy(update={
                        "failure_mode": canonical,
                        "severity": m_s,
                        "occurrence": m_o,
                        "detection": m_d,
                        "rpn": m_s * m_o * m_d,
                        "priority": priority,
                        "priority_reason": reason,
                    })

    # ── Track genuinely new scenarios (after dedup) ────────────────────────────
    new_scenario_names = [
        f.failure_mode for f in failures if f.failure_mode not in locked_rpn
    ]

    # ── Rule-based evaluation (zero LLM calls) ─────────────────────────────────
    evaluation = evaluate_pipeline(
        context=context,
        failures=failures,
        controls=controls,
        risks=risks,
        remediations=remediations,
        validations=validations,
        llm_calls=get_call_count(),
    )

    # ── LLM-as-judge (single batched call) ────────────────────────────────────
    with agent_span("llm_judge"):
        judge_verdicts = run_llm_judge(failures, risks, validations, remediations)

    # ── Eval persistence + drift detection ────────────────────────────────────
    eval_store.append_eval(evaluation, workspace)
    drift_alerts = eval_store.detect_drift(workspace)

    # ── Learning memory update ─────────────────────────────────────────────────
    update_from_run(failures, risks, workspace)

    # ── Fingerprint ────────────────────────────────────────────────────────────
    from memory.workspace_store import _fingerprint
    fingerprint = _fingerprint(code)

    # ── Scenario registry: persist new scenarios + save scan to DB ─────────────
    db_scan_id: int | None = None
    if workspace_id:
        if on_progress: on_progress("registry")
        register_new_scenarios(workspace_id, fingerprint, failures, risks, locked)
        import json as _json
        try:
            db_scan_id = _db.save_scan(
                workspace_id, fingerprint,
                _json.dumps({"fingerprint": fingerprint}, default=str),
                get_call_count(),
                0.0,
            )
            # Backfill run_id → scan_id so all agent spans written before
            # save_scan() are retrospectively linked to this scan row.
            if db_scan_id:
                run_id = get_run_id()
                if run_id:
                    _db.backfill_telemetry_scan_id(run_id, db_scan_id)
        except Exception:
            db_scan_id = None
        try:
            if db_scan_id:
                _db.save_eval(workspace_id, db_scan_id, evaluation.__dict__)
        except Exception:
            pass

    if on_progress: on_progress("eval")

    # ── Assemble result ────────────────────────────────────────────────────────
    result = {
        "context": context,
        "failures": failures,
        "controls": controls,
        "risks": risks,
        "remediations": remediations,
        "scenario_linkage": scenario_linkage,
        "validations": validations,
        "evaluation": evaluation,
        "judge_verdicts": judge_verdicts,
        "drift_alerts": drift_alerts,
        "workspace": workspace,
        "workspace_id": workspace_id,
        "db_scan_id": db_scan_id,
        "fingerprint": fingerprint,
        "from_cache": False,
        "registry_locked": bool(locked),
        "new_scenarios": new_scenario_names,
    }

    # Cache for next run (JSON file cache for fast repeated loads)
    cache_result(code, result, workspace)

    result["memory_stats"] = get_memory_stats(workspace)
    clear_scan_context()
    return result
