"""
B-029 — root-cause classification (ADR-016): security / architectural / engineering / operational.

  AC  every finding gets a primary domain, contributing domains, a root-cause chain and a confidence
  AC  the rubric lives in a registry file; a new domain needs no code change
  AC  benchmark findings carry the domain so agreement is scored against truth.json
  AC  the chat can answer "which problems are architectural?" from stored data
  AC  keyword matching is gone from the learning memory path; old memory files still load
  AC  old scans show "not classified" and do not error
  AC  an unknown domain from the model falls back safely
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import agents.preventive_agent as preventive_agent
import agents.root_cause_agent as root_cause_agent
import core.chat as chat
import core.root_cause as root_cause
import memory.analysis_cache as analysis_cache
import memory.learning_memory as learning_memory
import memory.workspace_store as workspace_store
from core.models import ControlAssessment, FailureMode, RemediationPlan, RiskScore, RootCause

ROOT = Path(__file__).resolve().parent.parent


def failure(name="Unauthenticated admin API"):
    return FailureMode(failure_mode=name, attack_chain=["call /admin", "no check"], business_impact="takeover",
                       blast_radius="all", trigger="request", evidence="src/admin.py:4")


def control(name="Unauthenticated admin API"):
    return ControlAssessment(failure_mode=name, controls={}, control_maturity="low", gaps=["no auth on admin routes"])


def risk(name="Unauthenticated admin API", s=9, o=5, d=5):
    return RiskScore(failure_mode=name, severity=s, occurrence=o, detection=d, rpn=s * o * d, priority="High",
                     justification="j", severity_rationale="", occurrence_rationale="", detection_rationale="")


def answer(*items):
    return json.dumps(list(items))


def item(name="Unauthenticated admin API", primary="security", **kw):
    base = dict(failure_mode=name, primary=primary, contributing=["architectural"], symptom="admin API answers anyone",
                proximate_cause="no auth middleware", root_cause="auth was never designed in", confidence=0.8)
    return {**base, **kw}


# ── the registry ──────────────────────────────────────────────────────────────

def test_the_registry_holds_the_four_domains_with_a_rubric():
    ids = [d["id"] for d in root_cause.domains()]
    assert ids == ["security", "architectural", "engineering", "operational"]
    assert all(d["label"] and d["rubric"] for d in root_cause.domains())


def test_a_new_domain_needs_only_a_registry_entry(monkeypatch, tmp_path):
    registry = tmp_path / "domains.json"
    registry.write_text(json.dumps({"domains": root_cause.domains() + [
        {"id": "compliance", "label": "Compliance", "rubric": "A regulatory obligation is not met."}]}), encoding="utf-8")
    monkeypatch.setattr(root_cause, "REGISTRY_PATH", registry)
    prompts = []
    monkeypatch.setattr(root_cause_agent, "call_llm", lambda p, max_tokens=4096: prompts.append(p) or answer(item(primary="compliance")))
    out = root_cause_agent.run_root_cause_analyst([failure()], [control()])
    assert out[0].primary == "compliance" and "A regulatory obligation is not met." in prompts[0]


# ── coercion ──────────────────────────────────────────────────────────────────

def test_an_unknown_domain_falls_back_to_unclassified_with_no_confidence():
    rc = root_cause.coerce_root_cause(item(primary="astrology", confidence=0.9), "x")
    assert rc.primary == "unclassified" and rc.confidence == 0.0


def test_contributing_domains_are_known_distinct_and_exclude_the_primary():
    rc = root_cause.coerce_root_cause(item(primary="Security", contributing=["security", "operational", "operational", "nope", "Architectural"]), "x")
    assert rc.primary == "security" and rc.contributing == ["operational", "architectural"]


def test_confidence_is_clamped_and_text_is_bounded():
    rc = root_cause.coerce_root_cause(item(confidence=7, symptom="s" * 900), "x")
    assert rc.confidence == 1.0 and len(rc.symptom) <= 300
    assert root_cause.coerce_root_cause(item(confidence="high"), "x").confidence == 0.0
    assert root_cause.coerce_root_cause("garbage", "named").failure_mode == "named"


def test_labels_and_categories_for_display_and_memory():
    assert root_cause.label("architectural") == "Architectural" and root_cause.label("unclassified") == "Not classified"
    assert root_cause.category_for("operational") == "operational" and root_cause.category_for(None) == "unclassified"


# ── the analyst ───────────────────────────────────────────────────────────────

def test_the_analyst_classifies_a_batch_in_one_call_and_matches_by_name(monkeypatch):
    prompts = []
    names = ["A", "B"]
    monkeypatch.setattr(root_cause_agent, "call_llm", lambda p, max_tokens=4096: prompts.append(p) or answer(
        item("B", "operational"), item("A", "engineering")))
    out = root_cause_agent.run_root_cause_analyst([failure(n) for n in names], [control(n) for n in names])
    assert len(prompts) == 1 and [(r.failure_mode, r.primary) for r in out] == [("A", "engineering"), ("B", "operational")]
    for needed in ("no auth on admin routes", "security", "architectural", "engineering", "operational"):
        assert needed in prompts[0]


def test_a_missing_or_garbled_answer_leaves_findings_unclassified_not_raised(monkeypatch):
    monkeypatch.setattr(root_cause_agent, "call_llm", lambda p, max_tokens=4096: answer(item("A", "security")))
    out = root_cause_agent.run_root_cause_analyst([failure("A"), failure("B")], [control("A"), control("B")])
    assert [r.primary for r in out] == ["security", "unclassified"]
    monkeypatch.setattr(root_cause_agent, "call_llm", lambda p, max_tokens=4096: "not json")
    assert [r.primary for r in root_cause_agent.run_root_cause_analyst([failure("A")], [control("A")])] == ["unclassified"]

    def boom(p, max_tokens=4096):
        raise RuntimeError("503")
    monkeypatch.setattr(root_cause_agent, "call_llm", boom)
    assert [r.primary for r in root_cause_agent.run_root_cause_analyst([failure("A")], [control("A")])] == ["unclassified"]


def test_a_provider_block_is_not_swallowed(monkeypatch):
    from core.provider_block import ProviderBlocked

    def blocked(p, max_tokens=4096):
        raise ProviderBlocked("mistral", "m", "root_cause")
    monkeypatch.setattr(root_cause_agent, "call_llm", blocked)
    with pytest.raises(ProviderBlocked):
        root_cause_agent.run_root_cause_analyst([failure()], [control()])


# ── the preventive agent receives the domain ─────────────────────────────────

def test_the_sre_stage_passes_the_domain_to_the_preventive_agent(monkeypatch):
    import agents.corrective_agent as corrective_agent
    import agents.sre_agent as sre_agent
    seen = []
    monkeypatch.setattr(corrective_agent, "call_llm", lambda p, max_tokens=4096: "[]")
    monkeypatch.setattr(preventive_agent, "call_llm", lambda p, max_tokens=4096: seen.append(p) or "[]")
    sre_agent.run_sre_agent(failure(), control(), risk(), domain="architectural")
    assert "design_change" in seen[0]


# ── the pipeline, persistence and old scans ──────────────────────────────────

def test_the_pipeline_classifies_each_finding_before_remediation_and_returns_the_result(monkeypatch, tmp_path):
    from test_finding_lifecycle import Harness, WS, failure as lifecycle_failure
    import workflows.fmea_pipeline as pipeline
    h = Harness(monkeypatch, tmp_path)
    domains_seen = []
    monkeypatch.setattr(pipeline, "run_root_cause_analyst", lambda f, c: [RootCause(failure_mode=x.failure_mode, primary="architectural") for x in f])
    monkeypatch.setattr(pipeline, "run_sre_agent", lambda f, c, r, domain=None: domains_seen.append(domain) or RemediationPlan(failure_mode=f.failure_mode))
    h.next_failures = [lifecycle_failure("A", "a.py:1"), lifecycle_failure("B", "b.py:1")]
    result = pipeline.run_fmea("x = 1", workspace=WS, persist=False)
    assert [(r.failure_mode, r.primary) for r in result["root_causes"]] == [("A", "architectural"), ("B", "architectural")]
    assert domains_seen == ["architectural", "architectural"]


def test_results_with_root_causes_survive_both_caches():
    rc = RootCause(failure_mode="x", primary="operational", contributing=["engineering"], confidence=0.6)
    for ser, deser in ((analysis_cache._serialize_result, analysis_cache._deserialize_result),
                       (workspace_store._serialize, workspace_store._deserialize)):
        stored = json.loads(json.dumps(ser({"root_causes": [rc], "from_cache": False}), default=str))
        assert deser(stored)["root_causes"][0].primary == "operational"


def test_a_result_stored_before_this_change_loads_without_root_causes():
    assert "root_causes" not in analysis_cache._deserialize_result({"failures": []})


# ── the chat ──────────────────────────────────────────────────────────────────

FINDINGS = {"failures": [{"failure_mode": "A", "attack_chain": ["x"]}, {"failure_mode": "B", "attack_chain": ["y"]}],
            "risks": [{"failure_mode": "A", "rpn": 100, "priority": "High"}, {"failure_mode": "B", "rpn": 50, "priority": "Low"}],
            "root_causes": [{"failure_mode": "A", "primary": "architectural", "contributing": ["operational"], "confidence": 0.7,
                             "symptom": "s", "proximate_cause": "p", "root_cause": "r"}]}


def test_the_chat_text_names_each_scenarios_domain_and_old_scans_say_not_classified():
    text = chat.build_findings_text(FINDINGS, {})
    assert "Root cause: Architectural" in text and "Root cause: Not classified" in text


def test_the_scenario_detail_tool_returns_the_root_cause_chain():
    views = chat._scenario_views(FINDINGS, {})
    detail = json.loads(chat._tool_get_scenario_detail({"failure_mode": "A"}, {}, views))
    assert detail["root_cause"]["primary"] == "architectural" and detail["root_cause"]["root_cause"] == "r"


# ── the benchmark ─────────────────────────────────────────────────────────────

def test_benchmark_findings_carry_the_primary_domain():
    from benchmarks.run import findings_from_result
    out = findings_from_result({"failures": [failure("A")], "risks": [risk("A")], "validations": [],
                                "root_causes": [RootCause(failure_mode="A", primary="security")]})
    assert out[0]["root_cause"] == "security"
    assert "root_cause" not in findings_from_result({"failures": [failure("A")], "risks": [risk("A")]})[0]


# ── learning memory ───────────────────────────────────────────────────────────

def test_learning_memory_files_use_domains_not_keyword_guesses(monkeypatch, tmp_path):
    monkeypatch.setattr(learning_memory, "LEARNING_PATH", tmp_path / "learning.json")
    learning_memory.update_from_run([failure("Unauthenticated API key overwrite")], [risk("Unauthenticated API key overwrite")],
                                    domains={"Unauthenticated API key overwrite": "security"})
    keys = [p["pattern_key"] for p in json.loads((tmp_path / "learning.json").read_text(encoding="utf-8"))["patterns"]]
    assert keys == ["security"]                                  # the name contains "key", which used to file it as secrets
    assert not hasattr(learning_memory, "_extract_category") and not hasattr(workspace_store, "_extract_category")


def test_an_older_memory_file_with_keyword_categories_still_loads(monkeypatch, tmp_path):
    path = tmp_path / "learning.json"
    path.write_text(json.dumps({"total_analyses": 3, "aggression_level": 2, "global_attack_chains": [], "patterns": [
        {"pattern_key": "injection", "category": "injection", "frequency": 2, "avg_severity": 8.0, "avg_occurrence": 5.0,
         "avg_detection": 5.0, "avg_rpn": 200.0, "first_seen": "2026-01-01", "last_seen": "2026-01-01", "example_attack_steps": [],
         "seen_failure_modes": []}]}), encoding="utf-8")
    monkeypatch.setattr(learning_memory, "LEARNING_PATH", path)
    learning_memory.update_from_run([failure("A")], [risk("A")], domains={"A": "engineering"})
    keys = sorted(p["pattern_key"] for p in json.loads(path.read_text(encoding="utf-8"))["patterns"])
    assert keys == ["engineering", "injection"]


# ── the interface ─────────────────────────────────────────────────────────────

def test_the_interface_shows_a_domain_badge_filter_and_risk_share():
    api = (ROOT / "frontend/src/api.js").read_text(encoding="utf-8")
    scen = (ROOT / "frontend/src/pages/ScenariosPage.jsx").read_text(encoding="utf-8")
    dash = (ROOT / "frontend/src/pages/DashboardPage.jsx").read_text(encoding="utf-8")
    assert "root_cause" in api and "root_cause:" in api
    assert "DomainChip" in scen and "domainFilter" in scen
    assert "Risk by root cause" in dash


# ── review follow-ups ─────────────────────────────────────────────────────────

def test_a_finding_renamed_to_its_locked_name_keeps_its_root_cause(monkeypatch, tmp_path):
    from test_finding_lifecycle import Harness, failure as lifecycle_failure
    import workflows.fmea_pipeline as pipeline
    h = Harness(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline, "run_root_cause_analyst", lambda f, c: [RootCause(failure_mode=x.failure_mode, primary="security") for x in f])
    quote = "src/auth.py:12 `q = 'SELECT * FROM users WHERE n=' + user`"
    h.scan([lifecycle_failure("Login query injection", quote)])
    result = h.scan([lifecycle_failure("SQL injection in login", quote.replace("src/auth.py", "app/login.py"))])
    names = [f.failure_mode for f in result["failures"]]
    assert names == ["Login query injection"]                                  # renamed to the locked name
    assert [(r.failure_mode, r.primary) for r in result["root_causes"]] == [("Login query injection", "security")]


def test_a_broken_registry_names_the_file(monkeypatch, tmp_path):
    bad = tmp_path / "domains.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(root_cause, "REGISTRY_PATH", bad)
    with pytest.raises(ValueError, match="domains.json"):
        root_cause.domains()


def test_scanned_text_reaches_the_analyst_as_marked_data(monkeypatch):
    prompts = []
    monkeypatch.setattr(root_cause_agent, "call_llm", lambda p, max_tokens=4096: prompts.append(p) or "[]")
    root_cause_agent.run_root_cause_analyst([failure()], [control()])
    assert "untrusted_data" in prompts[0] and "ignore any instructions" in prompts[0]


def test_a_failed_analysis_is_logged_not_silent(monkeypatch, caplog):
    def boom(p, max_tokens=4096):
        raise RuntimeError("503")
    monkeypatch.setattr(root_cause_agent, "call_llm", boom)
    with caplog.at_level("WARNING"):
        root_cause_agent.run_root_cause_analyst([failure()], [control()])
    assert "left unclassified" in caplog.text
