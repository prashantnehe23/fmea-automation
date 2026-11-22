"""
B-030 — corrective and preventive remediation (ADR-018): two agents, one Action shape, no dates.

  AC  each finding has corrective and preventive actions with kind, target, verification, owner role and urgency band
  AC  no dates, day ranges or Gantt fields are generated or shown anywhere
  AC  the evaluator checks: a corrective action with a verification, a preventive action, no action without a target
  AC  preventive actions differ by root-cause domain
  AC  the remediator builds diffs from corrective code_fix actions
  AC  old stored scans still render: fixes as corrective, monitoring and resilience upgrades as preventive
"""

import json
import re
import threading
from pathlib import Path

import pytest

import agents.corrective_agent as corrective_agent
import agents.evaluator as evaluator
import agents.llm_judge as llm_judge
import agents.preventive_agent as preventive_agent
import agents.remediator as remediator
import agents.sre_agent as sre_agent
from core.actions import CORRECTIVE_KINDS, OWNER_ROLES, PREVENTIVE_KINDS, coerce_actions, plan_actions, urgency_for
from core.models import Action, ControlAssessment, FailureMode, RemediationPlan, RiskScore

ROOT = Path(__file__).resolve().parent.parent


def failure(name="SQL injection in login", evidence="src/auth.py:12 `q = 'SELECT * FROM users WHERE n=' + user`"):
    return FailureMode(failure_mode=name, attack_chain=["send crafted name", "query runs"], business_impact="data loss",
                       blast_radius="all users", trigger="login request", evidence=evidence)


def risk(priority="High", s=9, o=6, d=5):
    return RiskScore(failure_mode="SQL injection in login", severity=s, occurrence=o, detection=d, rpn=s * o * d, priority=priority,
                     justification="j", severity_rationale="", occurrence_rationale="", detection_rationale="")


CONTROL = ControlAssessment(failure_mode="SQL injection in login", controls={}, control_maturity="low", gaps=["no parameterised queries"])


def action(**kw):
    base = dict(id="c1", title="Parameterise the query", detail="Use bound parameters", kind="code_fix", target="src/auth.py",
                verification="A test sends a quote in the name and gets no rows", owner_role="developer", urgency="now")
    return Action(**{**base, **kw})


# ── urgency: an ordering hint derived from risk and kind, never a date ────────

@pytest.mark.parametrize("kind,priority,band", [
    ("containment", "Critical", "now"), ("containment", "Medium", "now"), ("containment", "Low", "next"),
    ("code_fix", "Critical", "now"), ("code_fix", "High", "now"), ("code_fix", "Medium", "next"), ("code_fix", "Low", "later"),
    ("guardrail", "Critical", "next"), ("guardrail", "Medium", "later"), ("design_change", "High", "next"),
    ("monitoring", "Critical", "now"), ("monitoring", "Medium", "next"), ("runbook", "Low", "later"),
    ("something_else", "High", "now"),
])
def test_urgency_band_follows_risk_and_kind(kind, priority, band):
    assert urgency_for(kind, priority) == band


# ── coercion of model answers ─────────────────────────────────────────────────

def test_actions_are_coerced_from_untidy_model_answers():
    raw = {"actions": [
        {"title": "Parameterise the query", "detail": "bound params", "kind": "CODE_FIX", "target": "src/auth.py:12",
         "verification": "regression test", "owner_role": "dev"},
        "Add a WAF rule",
        {"title": "x" * 500, "kind": "not-a-kind", "owner_role": "Security team"},
        {"detail": "no title at all"},
        42,
    ]}
    acts = coerce_actions(raw, side="corrective", failure=failure(), risk=risk("Critical"))
    assert [a.id for a in acts] == ["c1", "c2", "c3", "c4"]
    first, second, third, fourth = acts
    assert (first.kind, first.owner_role, first.urgency, first.target) == ("code_fix", "developer", "now", "src/auth.py:12")
    assert second.title == "Add a WAF rule" and second.kind in CORRECTIVE_KINDS and second.verification == ""
    assert len(third.title) <= 160 and third.kind == "code_fix" and third.owner_role == "security"
    assert fourth.title                                                        # a title is always present
    assert all(a.owner_role in OWNER_ROLES and a.urgency in ("now", "next", "later") for a in acts)


def test_a_missing_target_falls_back_to_the_findings_file_or_stays_empty():
    acts = coerce_actions([{"title": "Fix it", "kind": "code_fix"}], side="corrective", failure=failure(), risk=risk())
    assert acts[0].target == "src/auth.py"
    none = coerce_actions([{"title": "Fix it"}], side="corrective", failure=failure(evidence=""), risk=risk())
    assert none[0].target == ""                                                # left empty so that the evaluator flags it


def test_preventive_kinds_and_a_bounded_list():
    acts = coerce_actions([{"title": f"a{i}", "kind": "monitoring"} for i in range(20)], side="preventive", failure=failure(), risk=risk())
    assert len(acts) == 6 and all(a.kind in PREVENTIVE_KINDS and a.id.startswith("p") for a in acts)
    assert coerce_actions("not json at all", side="corrective", failure=failure(), risk=risk()) == []


# ── the two agents ────────────────────────────────────────────────────────────

CORRECTIVE_ANSWER = json.dumps({"actions": [
    {"title": "Parameterise the query", "detail": "Use bound parameters in login()", "kind": "code_fix", "target": "src/auth.py",
     "verification": "A test sends a quote in the name and expects no rows", "owner_role": "developer"},
    {"title": "Rotate exposed credentials", "kind": "containment", "target": "database", "verification": "Old credentials are refused", "owner_role": "security"},
]})
PREVENTIVE_ANSWER = json.dumps({"actions": [
    {"title": "Ban string-built SQL in CI", "kind": "guardrail", "target": "CI pipeline", "verification": "The lint rule fails on a concatenated query", "owner_role": "developer"},
]})


def capture(monkeypatch, module, answer):
    prompts = []
    monkeypatch.setattr(module, "call_llm", lambda prompt, max_tokens=4096: prompts.append(prompt) or answer)
    return prompts


def test_the_corrective_agent_returns_structured_actions(monkeypatch):
    prompts = capture(monkeypatch, corrective_agent, CORRECTIVE_ANSWER)
    acts = corrective_agent.run_corrective_agent(failure(), CONTROL, risk("Critical"))
    assert [(a.kind, a.urgency) for a in acts] == [("code_fix", "now"), ("containment", "now")]
    assert all(a.verification for a in acts)
    prompt = prompts[0]
    assert "SQL injection in login" in prompt and "no parameterised queries" in prompt and "kind" in prompt
    assert "verification" in prompt and "owner_role" in prompt


def test_the_preventive_agent_returns_structured_actions(monkeypatch):
    capture(monkeypatch, preventive_agent, PREVENTIVE_ANSWER)
    acts = preventive_agent.run_preventive_agent(failure(), CONTROL, risk("Critical"))
    assert [(a.kind, a.urgency, a.id) for a in acts] == [("guardrail", "next", "p1")]


def test_preventive_actions_differ_by_root_cause_domain(monkeypatch):
    prompts = capture(monkeypatch, preventive_agent, "[]")
    preventive_agent.run_preventive_agent(failure(), CONTROL, risk(), "architectural")
    preventive_agent.run_preventive_agent(failure(), CONTROL, risk(), "operational")
    preventive_agent.run_preventive_agent(failure(), CONTROL, risk(), None)
    architectural, operational, general = prompts
    assert "design" in architectural.lower() and "design_change" in architectural
    assert "monitoring" in operational.lower() and "runbook" in operational
    assert architectural != operational != general and "design_change" not in operational.split("Focus")[-1][:400]
    assert "unknown_domain" not in general


def test_default_kinds_follow_the_domain_when_the_model_names_none(monkeypatch):
    capture(monkeypatch, preventive_agent, json.dumps([{"title": "Do something"}]))
    arch = preventive_agent.run_preventive_agent(failure(), CONTROL, risk(), "architectural")[0]
    ops = preventive_agent.run_preventive_agent(failure(), CONTROL, risk(), "operational")[0]
    assert arch.kind == "design_change" and ops.kind == "monitoring"


def test_a_bad_model_answer_gives_an_empty_list_not_a_crash(monkeypatch):
    capture(monkeypatch, corrective_agent, "I cannot produce JSON")
    assert corrective_agent.run_corrective_agent(failure(), CONTROL, risk()) == []
    capture(monkeypatch, preventive_agent, "oops")
    assert preventive_agent.run_preventive_agent(failure(), CONTROL, risk()) == []


def test_the_sre_stage_runs_both_agents_in_parallel_and_assembles_one_plan(monkeypatch):
    barrier = threading.Barrier(2, timeout=5)                                  # both calls must be in flight together

    def corrective(prompt, max_tokens=4096):
        barrier.wait()
        return CORRECTIVE_ANSWER

    def preventive(prompt, max_tokens=4096):
        barrier.wait()
        return PREVENTIVE_ANSWER

    monkeypatch.setattr(corrective_agent, "call_llm", corrective)
    monkeypatch.setattr(preventive_agent, "call_llm", preventive)
    plan = sre_agent.run_sre_agent(failure(), CONTROL, risk())
    assert isinstance(plan, RemediationPlan) and plan.failure_mode == "SQL injection in login"
    assert [a.id for a in plan.corrective] == ["c1", "c2"] and [a.id for a in plan.preventive] == ["p1"]


def test_usage_from_both_parallel_agents_is_counted_for_the_scan(monkeypatch):
    import core.llm as llm

    def counting(module):
        def call(prompt, max_tokens=4096):
            llm._add_usage(calls=1, prompt=10, completion=5)
            return "[]"
        monkeypatch.setattr(module, "call_llm", call)

    counting(corrective_agent)
    counting(preventive_agent)
    llm.reset_call_count()
    sre_agent.run_sre_agent(failure(), CONTROL, risk())
    assert llm.get_call_count() == 2 and llm.get_token_usage() == (20, 10)


def test_a_provider_block_in_either_agent_propagates(monkeypatch):
    from core.provider_block import ProviderBlocked

    def boom(prompt, max_tokens=4096):
        raise ProviderBlocked("mistral", "m", "sre")

    monkeypatch.setattr(corrective_agent, "call_llm", lambda p, max_tokens=4096: CORRECTIVE_ANSWER)
    monkeypatch.setattr(preventive_agent, "call_llm", boom)
    with pytest.raises(ProviderBlocked):
        sre_agent.run_sre_agent(failure(), CONTROL, risk())


# ── no dates anywhere ─────────────────────────────────────────────────────────

BANNED = re.compile(r"roadmap_90_day|roadmap_tasks|RoadmapTask|Gantt|Day 30|Day 60|Day 90|start_day|end_day|dependency_notes|rpn_priority_note")


def test_no_roadmap_dates_or_gantt_fields_exist_in_code_prompts_or_the_ui():
    offenders = []
    for folder in ("agents", "core", "workflows", "api", "memory", "frontend/src"):
        for f in (ROOT / folder).rglob("*"):
            if f.suffix in {".py", ".jsx", ".js"} and "node_modules" not in f.parts and BANNED.search(f.read_text(encoding="utf-8")):
                offenders.append(str(f.relative_to(ROOT)))
    for name in ("dashboard.py", "app.py"):
        if BANNED.search((ROOT / name).read_text(encoding="utf-8")):
            offenders.append(name)
    assert offenders == []
    assert not {"roadmap_90_day", "roadmap_tasks"} & set(RemediationPlan.model_fields)


def test_the_agents_prompts_ask_for_no_dates(monkeypatch):
    prompts = capture(monkeypatch, corrective_agent, "[]") + capture(monkeypatch, preventive_agent, "[]")
    corrective_agent.run_corrective_agent(failure(), CONTROL, risk())
    preventive_agent.run_preventive_agent(failure(), CONTROL, risk(), "security")
    for p in prompts:
        assert not re.search(r"\bday \d+|\b\d+[- ]day\b|\bweek\b|\bdeadline\b|\bsprint\b|start_day|\bquarter\b", p, re.IGNORECASE), p[:200]


# ── the evaluator ─────────────────────────────────────────────────────────────

def sre_eval(plan):
    return evaluator._eval_sre([plan], [failure()])


def test_the_evaluator_requires_a_verified_corrective_action_a_preventive_action_and_targets():
    good = RemediationPlan(failure_mode="x", corrective=[action()], preventive=[action(id="p1", kind="guardrail")])
    assert sre_eval(good).passed
    no_verification = RemediationPlan(failure_mode="x", corrective=[action(verification="")], preventive=[action(id="p1", kind="guardrail")])
    assert any("verification" in i for i in sre_eval(no_verification).issues)
    no_preventive = RemediationPlan(failure_mode="x", corrective=[action()], preventive=[])
    assert any("preventive" in i for i in sre_eval(no_preventive).issues)
    no_target = RemediationPlan(failure_mode="x", corrective=[action(target="")], preventive=[action(id="p1", kind="guardrail")])
    assert any("target" in i for i in sre_eval(no_target).issues)


def test_the_evaluator_no_longer_wants_a_30_60_90_roadmap_and_skips_legacy_plans():
    legacy = RemediationPlan(failure_mode="x", fixes=["old fix"], monitoring=["old monitor"], resilience_upgrades=["old upgrade"])
    result = sre_eval(legacy)
    assert result.passed and not any("roadmap" in i.lower() or "day" in i.lower() for i in result.issues + result.warnings)


def test_the_judge_sees_action_counts_not_roadmap_fields():
    plan = RemediationPlan(failure_mode="x", corrective=[action()], preventive=[action(id="p1", kind="guardrail"), action(id="p2", kind="runbook")])
    prompt = llm_judge._build_prompt([failure()], [risk()], [], [plan])
    assert "corrective_count" in prompt and "preventive_count" in prompt and "roadmap" not in prompt.lower()


# ── the remediator ────────────────────────────────────────────────────────────

def test_the_remediator_builds_diffs_from_corrective_code_fix_actions(monkeypatch):
    prompts = []
    monkeypatch.setattr(remediator, "call_llm", lambda prompt, max_tokens=4096: prompts.append(prompt) or "{}")
    plan = RemediationPlan(failure_mode="SQL injection in login", corrective=[
        action(title="Parameterise the query"), action(id="c2", title="Rotate credentials", kind="containment"),
        action(id="c3", title="Validate the name length", kind="code_fix")], preventive=[action(id="p1", title="Add a lint rule", kind="guardrail")])
    try:
        remediator.generate_fix(failure(), plan, "def login(u):\n    pass\n")
    except Exception:
        pass
    prompt = prompts[0]
    assert "Parameterise the query" in prompt and "Validate the name length" in prompt
    assert "Rotate credentials" not in prompt and "Add a lint rule" not in prompt


def test_the_remediator_still_uses_fixes_of_legacy_plans(monkeypatch):
    prompts = []
    monkeypatch.setattr(remediator, "call_llm", lambda prompt, max_tokens=4096: prompts.append(prompt) or "{}")
    legacy = RemediationPlan(failure_mode="x", fixes=["Use prepared statements"])
    try:
        remediator.generate_fix(failure(), legacy, "def login(u):\n    pass\n")
    except Exception:
        pass
    assert "Use prepared statements" in prompts[0]


# ── old stored scans keep rendering ───────────────────────────────────────────

OLD_PLAN = {"failure_mode": "x", "fixes": ["Use prepared statements", "Validate input"], "monitoring": ["Alert on SQL errors"],
            "resilience_upgrades": ["Least-privilege database user"],
            "roadmap_90_day": {"Day 30": "fix"}, "roadmap_tasks": [{"task_id": "t1", "title": "t", "start_day": 1, "end_day": 5}],
            "dependency_notes": "", "rpn_priority_note": ""}


def test_an_old_stored_plan_loads_and_maps_fixes_to_corrective_and_the_rest_to_preventive():
    plan = RemediationPlan(**OLD_PLAN)                                        # extra stored fields are ignored
    corrective, preventive = plan_actions(plan)
    assert [a.title for a in corrective] == ["Use prepared statements", "Validate input"]
    assert [a.kind for a in preventive] == ["monitoring", "design_change"]
    assert all(a.urgency in ("now", "next", "later") for a in corrective + preventive)
    assert "roadmap_90_day" not in plan.model_dump()


def test_a_new_plan_survives_a_cache_round_trip():
    from memory.analysis_cache import _deserialize_result, _serialize_result
    plan = RemediationPlan(failure_mode="x", corrective=[action()], preventive=[action(id="p1", kind="guardrail")])
    stored = json.loads(json.dumps(_serialize_result({"remediations": [plan], "from_cache": False})))
    restored = _deserialize_result(stored)["remediations"][0]
    assert restored.corrective[0].title == "Parameterise the query" and restored.preventive[0].kind == "guardrail"


def test_the_chat_scenario_detail_shows_structured_actions_for_new_and_old_plans():
    import core.chat as chat
    new = RemediationPlan(failure_mode="x", corrective=[action()], preventive=[action(id="p1", kind="guardrail")]).model_dump()
    out_new = chat.plan_detail(new)
    assert out_new["corrective"][0]["verification"] and out_new["preventive"][0]["kind"] == "guardrail"
    out_old = chat.plan_detail(OLD_PLAN)
    assert [a["title"] for a in out_old["corrective"]] == ["Use prepared statements", "Validate input"]
    assert "roadmap_90_day" not in json.dumps(out_old)


# ── the backlog ───────────────────────────────────────────────────────────────

def test_b010_is_marked_superseded_in_the_backlog():
    text = (ROOT / "docs" / "BACKLOG.md").read_text(encoding="utf-8")
    assert re.search(r"B-010[^\n]*(superseded|Superseded)", text)


# ── review follow-ups ─────────────────────────────────────────────────────────

def test_a_preventive_action_never_borrows_the_findings_file_and_odd_tokens_are_not_paths():
    prev = coerce_actions([{"title": "Add a CI gate", "kind": "guardrail"}], side="preventive", failure=failure(), risk=risk())
    assert prev[0].target == ""
    odd = coerce_actions([{"title": "Fix"}], side="corrective", failure=failure(evidence="e.g. see example.com v1.2"), risk=risk())
    assert odd[0].target == ""


def test_owner_roles_match_whole_words():
    def role(text):
        return coerce_actions([{"title": "x", "owner_role": text}], side="corrective", failure=failure(), risk=risk())[0].owner_role
    assert (role("DevOps"), role("device vendor"), role("SRE team"), role("Product owner")) == ("sre", "developer", "sre", "product")


def test_one_agent_failing_ordinarily_keeps_the_other_agents_result(monkeypatch):
    def broken(prompt, max_tokens=4096):
        raise RuntimeError("503")
    monkeypatch.setattr(corrective_agent, "call_llm", broken)
    monkeypatch.setattr(preventive_agent, "call_llm", lambda p, max_tokens=4096: PREVENTIVE_ANSWER)
    plan = sre_agent.run_sre_agent(failure(), CONTROL, risk())
    assert plan.corrective == [] and [a.id for a in plan.preventive] == ["p1"]


def test_the_spend_limit_counts_every_call_from_several_threads(monkeypatch):
    import core.budget as budget
    monkeypatch.setattr(budget, "compute_cost", lambda m, p, c: 0.01)
    with budget.spend_limit(1000.0) as tracker:
        def work():
            for _ in range(500):
                budget.record("m", 1, 1)
        import contextvars
        threads = [threading.Thread(target=contextvars.copy_context().run, args=(work,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert round(tracker.spent_usd, 2) == 20.0


def test_a_malformed_stored_action_does_not_break_the_chat_tool():
    import core.chat as chat
    assert chat.plan_detail({"failure_mode": "x", "corrective": [{"id": "c1"}]})["corrective"] == []
