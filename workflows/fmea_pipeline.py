from __future__ import annotations

import logging

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
from core.batch_merge import merge_contexts, merge_failures, merge_linkage
from core.llm import get_call_count, reset_call_count
from core.models import ControlAssessment, RemediationPlan
from core.priority import exploit_confirmed_from, guarded_severity, priority_for
from core.telemetry import agent_span, clear_scan_context, get_run_id, set_scan_context
from memory import eval_store, workspace_store
import memory.db as _db
from memory.scenario_registry import (
    clear_registry,
    expected_names,
    find_by_identity,
    find_matching_scenario,
    fix_candidates,
    get_locked_scenarios,
    previous_names,
    record_scan_outcome,
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


def _refresh_lifecycle(cached: dict, workspace) -> None:
    """A cached scan is shown again, possibly after people decided things or the code was reverted: apply the
    lifecycle rules to the registry and replace the stale lifecycle fields stored with the cached result."""
    cached["lifecycle_changes"], cached["fix_candidates"] = {}, []
    if workspace is None:
        return
    try:
        workspace_id = _db.upsert_workspace(workspace)
        cached["lifecycle_changes"] = record_scan_outcome(
            workspace_id, None, list(cached.get("failures") or []), get_locked_scenarios(workspace_id), confirm_new=False)
        cached["fix_candidates"] = fix_candidates(workspace_id)
    except Exception:
        logging.getLogger(__name__).warning("finding lifecycle refresh failed", exc_info=True)


# Agents that answer for a whole list of findings in one call get at most this many at a time: with no cap on
# findings (B-028 phase 0) one call over dozens of them would run out of output tokens and silently lose items.
AGENT_CHUNK = 10
# One remediation call is made per finding; beyond this many per scan the rest get a placeholder (spend guard).
MAX_REMEDIATION_PLANS = 30


def _chunks(n: int):
    return [(s, min(s + AGENT_CHUNK, n)) for s in range(0, n, AGENT_CHUNK)] or [(0, 0)]


def _assess(failures: list, prompt_code: str) -> tuple[list, list]:
    """Linkage reports and one control assessment per finding, asked for in chunks."""
    reports, controls = [], []
    for s, e in _chunks(len(failures)):
        group = failures[s:e]
        reports.append(run_scenario_linkage(group, prompt_code))
        got = list(run_controls_assessor(group, prompt_code))
        got += [ControlAssessment(failure_mode=f.failure_mode, controls={}, control_maturity="Unknown", gaps=["not assessed"])
                for f in group[len(got):]]
        controls += got[:len(group)]
    return reports, controls


# Demo / predictable billing: at most this many failure modes (2 + 2*N API calls).
DEFAULT_MAX_FAILURE_MODES = 7


def run_fmea(
    code: str,
    *,
    max_failure_modes: int | None = DEFAULT_MAX_FAILURE_MODES,
    force_rerun: bool = False,
    workspace=None,
    on_progress=None,
    scope: dict | None = None,
    batches: list[str] | None = None,
    persist: bool = True,
) -> dict:
    """
    Run the full FMEA pipeline with caching, learning, validation, and evaluation.

    max_failure_modes: None = report everything the agents find (B-028 phase 0); a number keeps the old cap.
    persist: False runs the scan without touching any record (registry, lifecycle history, scan log, caches, learning
             memory): used by the pull-request check, whose branch must not change what the default branch knows (B-012).
    batches: the code split into passes for a large repository; each is scanned on its own and the findings merged.
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
    if persist and not force_rerun:
        cached = get_cached_result(code, workspace)
        if cached is not None:
            cached["memory_stats"] = get_memory_stats(workspace)
            cached["scope"] = scope
            _refresh_lifecycle(cached, workspace)
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
    locked_names: list[str] = expected_names(locked)         # fixed findings and fix candidates may stay out (B-031)
    # Locked findings never take a new finding's place: they do not count against the cap (ADR-019)
    cap = None if max_failure_modes is None else max_failure_modes + len(locked_names)
    locked_rpn: dict[str, dict] = {row["failure_mode"]: row for row in locked}

    # ── Learning context injection ─────────────────────────────────────────────
    learning_ctx = get_learning_context(workspace)

    # ── Set telemetry context (scan_id not yet known; workspace_id is enough) ──
    set_scan_context(scan_id=None, workspace_id=workspace_id)

    # ── Core pipeline ──────────────────────────────────────────────────────────
    # Agents see numbered lines so the line numbers they cite are real (B-041); the original
    # text is what is cached, fingerprinted and stored.
    parts = list(batches) if batches and len(batches) > 1 else [code]
    prompt_codes = [number_lines(c) for c in parts]
    multi = len(parts) > 1

    if on_progress: on_progress("surveyor")
    with agent_span("surveyor"):
        contexts = [run_surveyor(pc, business_context=biz_ctx) for pc in prompt_codes]
    context = merge_contexts(contexts) if multi else contexts[0]

    if on_progress: on_progress("saboteur")
    with agent_span("saboteur"):
        per_batch = [
            run_saboteur(
                pc, contexts[i],
                max_scenarios=cap,
                learning_context=learning_ctx,
                locked_names=locked_names if locked_names else None,
                previous_names=previous_names(locked) or None,
                **({"part": (i + 1, len(parts))} if multi else {}),
            )
            for i, pc in enumerate(prompt_codes)
        ]
    failures, origin = merge_failures(per_batch) if multi else (per_batch[0], [0] * len(per_batch[0]))
    if cap is not None:
        # Locked findings are never cut by the cap, wherever they sit; new findings fill the rest
        room = max_failure_modes
        keep = []
        for k, f in enumerate(failures):
            if f.failure_mode in locked_names:
                keep.append(k)
            elif room > 0:
                keep.append(k)
                room -= 1
        failures, origin = [failures[k] for k in keep], [origin[k] for k in keep]

    if on_progress: on_progress("controls")
    with agent_span("controls"):
        reports, controls = [], [None] * len(failures)
        for i, pc in enumerate(prompt_codes):
            idx = [k for k, o in enumerate(origin) if o == i]
            if not idx:
                continue
            group_reports, group_controls = _assess([failures[k] for k in idx], pc)
            reports += group_reports
            for k, assessment in zip(idx, group_controls):
                controls[k] = assessment
        scenario_linkage = reports[0] if len(reports) == 1 else merge_linkage(reports)

    # Single batched actuary call — locked scenarios short-circuit (no LLM call)
    if on_progress: on_progress("actuary")
    with agent_span("actuary"):
        risks = []
        for s_, e_ in _chunks(len(failures)):
            risks += score_all_failures(
                failures[s_:e_], controls[s_:e_], context,
                business_context=biz_ctx,
                locked_rpn=locked_rpn if locked_rpn else None,
            )

    # Per-failure SRE (complex plans benefit from focused attention)
    if on_progress: on_progress("sre")
    with agent_span("sre"):
        by_risk = sorted(range(len(risks)), key=lambda k: -risks[k].rpn)
        planned = set(by_risk[:MAX_REMEDIATION_PLANS])
        remediations = [
            run_sre_agent(f, c, r) if k in planned else RemediationPlan(
                failure_mode=f.failure_mode, monitoring=[], resilience_upgrades=[], roadmap_90_day={},
                fixes=[f"Not generated: the limit of {MAX_REMEDIATION_PLANS} remediation plans per scan was reached "
                       "(highest risk first). Ask in the results chat or rescan."])
            for k, (f, c, r) in enumerate(zip(failures, controls, risks))
        ]
        skipped_plans = [failures[k].failure_mode for k in range(len(failures)) if k not in planned]

    # ── Validator (single batched call) ────────────────────────────────────────
    if on_progress: on_progress("validator")
    with agent_span("validator"):
        validations = []
        for s_, e_ in _chunks(len(failures)):
            validations += run_validator(failures[s_:e_], risks[s_:e_])

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
        claimed = {f.failure_mode for f in failures if f.failure_mode in locked_rpn}     # one finding, one result
        for i, (f, r) in enumerate(zip(failures, risks)):
            if f.failure_mode not in locked_rpn:
                match = find_by_identity(f, locked) or find_matching_scenario(f.failure_mode, list(f.attack_chain), locked)
                if match and match["failure_mode"] not in claimed:
                    canonical = match["failure_mode"]
                    claimed.add(canonical)
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
        # The judge rates the run as a whole from a sample: the highest-risk findings, at most one chunk
        top = sorted(range(len(risks)), key=lambda k: -risks[k].rpn)[:AGENT_CHUNK] if len(risks) > AGENT_CHUNK else None
        judge_verdicts = (run_llm_judge(failures, risks, validations, remediations) if top is None else run_llm_judge(
            [failures[k] for k in sorted(top)], [risks[k] for k in sorted(top)],
            [validations[k] for k in sorted(top)], [remediations[k] for k in sorted(top)]))

    # ── Eval persistence + drift detection ────────────────────────────────────
    drift_alerts = []
    if persist:
        eval_store.append_eval(evaluation, workspace)
        drift_alerts = eval_store.detect_drift(workspace)

    # ── Learning memory update ─────────────────────────────────────────────────
    if persist:
        update_from_run(failures, risks, workspace)

    # ── Fingerprint ────────────────────────────────────────────────────────────
    from memory.workspace_store import _fingerprint
    fingerprint = _fingerprint(code)

    # ── Scenario registry: persist new scenarios + save scan to DB ─────────────
    db_scan_id: int | None = None
    lifecycle_changes: dict = {}
    pending_fixes: list[dict] = []
    if workspace_id and persist:
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
        try:
            lifecycle_changes = record_scan_outcome(workspace_id, db_scan_id, failures, locked)
            pending_fixes = fix_candidates(workspace_id)
        except Exception:
            logging.getLogger(__name__).warning("finding lifecycle bookkeeping failed", exc_info=True)
            lifecycle_changes, pending_fixes = {}, []     # lifecycle bookkeeping must never fail a scan

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
        "lifecycle_changes": lifecycle_changes,   # B-031: what this scan changed (new, regressed, fix candidates)
        "fix_candidates": pending_fixes,           # B-031: findings waiting for a person to confirm they are fixed
        "scope": scope,                    # B-033: what was examined and what was not
        "batches": len(parts),             # B-028 phase 0: passes over the code
        "remediation_limit": {"limit": MAX_REMEDIATION_PLANS, "skipped": skipped_plans},   # spend guard (placeholders)
    }

    # Cache for next run (JSON file cache for fast repeated loads)
    if persist:
        cache_result(code, result, workspace)

    result["memory_stats"] = get_memory_stats(workspace)
    clear_scan_context()
    return result
