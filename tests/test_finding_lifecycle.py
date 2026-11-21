"""
B-031 — finding identity, lifecycle and lock semantics (ADR-019).

  AC1  locked findings never take a new finding's place (the old cap problem)
  AC2  locked scores and expert adjustments survive a rescan of changed code
  AC3  a locked finding the code no longer shows becomes a fix candidate for confirmation
  AC4  a fixed finding that returns becomes regressed
  AC5  existing registry rows migrate without losing locked scores
  AC6  identity survives a rename of the scenario text and a file move
"""

import json
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import core.findings as findings
import memory.db as db
import memory.scenario_registry as registry
import workflows.fmea_pipeline as pipeline
from core.models import ControlAssessment, FailureMode, RemediationPlan, RiskScore, ScenarioLinkageReport, SystemContext, ValidationResult

WS = SimpleNamespace(customer="Shop", project="api", function="", business_tier="Tier 1",
                     user_type="external_customers", business_context="", customer_learning=True)


def failure(name, evidence="", chain=None):
    return FailureMode(failure_mode=name, attack_chain=chain or ["step one", "step two"], business_impact="impact",
                       blast_radius="blast", trigger="trigger", evidence=evidence)


class Harness:
    """Runs the real run_fmea with every model-backed agent replaced by a scripted fake."""

    def __init__(self, monkeypatch, tmp_path):
        self.next_failures: list[FailureMode] = []
        self.saboteur_calls: list[dict] = []
        monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fmea.db")
        monkeypatch.setattr(pipeline, "run_surveyor", lambda code, business_context="": SystemContext(
            tiering={}, attack_surfaces=[], failure_domains=[]))
        monkeypatch.setattr(pipeline, "run_saboteur", self._saboteur)
        monkeypatch.setattr(pipeline, "run_scenario_linkage", lambda f, c: ScenarioLinkageReport(explanations=[]))
        monkeypatch.setattr(pipeline, "run_controls_assessor", lambda f, c: [
            ControlAssessment(failure_mode=x.failure_mode, controls={}, control_maturity="Low", gaps=[]) for x in f])
        monkeypatch.setattr(pipeline, "score_all_failures", self._score)
        monkeypatch.setattr(pipeline, "run_sre_agent", lambda f, c, r: RemediationPlan(
            failure_mode=f.failure_mode, fixes=[], monitoring=[], resilience_upgrades=[], roadmap_90_day={}))
        monkeypatch.setattr(pipeline, "run_validator", lambda f, r: [ValidationResult(failure_mode=x.failure_mode) for x in f])
        monkeypatch.setattr(pipeline, "run_llm_judge", lambda *a, **k: [])
        monkeypatch.setattr(pipeline, "evaluate_pipeline", lambda **k: SimpleNamespace(__dict__={}, overall_passed=True))
        monkeypatch.setattr(pipeline.eval_store, "append_eval", lambda *a, **k: None)
        monkeypatch.setattr(pipeline.eval_store, "detect_drift", lambda *a, **k: [])
        import memory.workspace_store as ws_store
        monkeypatch.setattr(ws_store, "get_cached_result", lambda *a, **k: None)
        monkeypatch.setattr(ws_store, "cache_result", lambda *a, **k: None)
        monkeypatch.setattr(ws_store, "update_from_run", lambda *a, **k: None)
        monkeypatch.setattr(ws_store, "get_learning_context", lambda *a, **k: "")
        monkeypatch.setattr(ws_store, "get_memory_stats", lambda *a, **k: {})
        monkeypatch.setattr(registry, "embed_text", lambda text: (_ for _ in ()).throw(RuntimeError("no embeddings in tests")))

    def _saboteur(self, code, context, **kw):
        self.saboteur_calls.append(kw)
        return list(self.next_failures)

    @staticmethod
    def _score(failures, controls, context, business_context="", locked_rpn=None):
        out = []
        for f in failures:
            row = (locked_rpn or {}).get(f.failure_mode)
            s, o, d = (row["severity"], row["occurrence"], row["detection"]) if row else (8, 5, 5)
            out.append(RiskScore(failure_mode=f.failure_mode, severity=s, occurrence=o, detection=d, rpn=s * o * d,
                                 priority="High", justification="j", severity_rationale="", occurrence_rationale="",
                                 detection_rationale=""))
        return out

    def scan(self, failures, code="code v1", **kw):
        self.next_failures = failures
        return pipeline.run_fmea(code, workspace=WS, force_rerun=True, **kw)

    def states(self, ws_id):
        return {r["failure_mode"]: r["state"] for r in db.get_locked_scenarios(ws_id)}


@pytest.fixture
def h(monkeypatch, tmp_path):
    return Harness(monkeypatch, tmp_path)


# ── identity ──────────────────────────────────────────────────────────────────

def test_identity_ignores_the_scenario_name_and_the_file_path():
    a = findings.finding_identity("src/auth.py:12 `q = 'SELECT * FROM users WHERE n=' + user`")
    b = findings.finding_identity("app/accounts/login.py:3-4  q = 'select * from users where n=' + user")
    assert a is not None and a == b


def test_identity_differs_for_different_code_and_is_none_without_a_quote():
    a = findings.finding_identity("a.py:1 `os.system('ping ' + request.args['host'])`")
    b = findings.finding_identity("a.py:1 `eval(request.args['expression'])`")
    assert a != b
    assert findings.finding_identity("") is None and findings.finding_identity(None) is None
    assert findings.finding_identity("a.py:1") is None
    assert findings.finding_identity("a.py:9 `return x`") is None          # too generic to identify one weakness


def test_a_renamed_finding_in_a_moved_file_is_matched_by_identity_and_keeps_its_locked_scores(h):
    first = h.scan([failure("SQL injection in login", "src/auth.py:12 `q = 'SELECT * FROM users WHERE n=' + user`")])
    ws = first["workspace_id"]
    second = h.scan([failure("Unsafe query construction", "app/accounts/login.py:3 `q = 'SELECT * FROM users WHERE n=' + user`")],
                    code="code v2 (file moved)")
    assert [f.failure_mode for f in second["failures"]] == ["SQL injection in login"]       # canonical name restored
    assert second["new_scenarios"] == []
    assert h.states(ws) == {"SQL injection in login": "confirmed"}


# ── AC1: locked findings do not take a new finding's place ────────────────────

def test_seven_locked_findings_plus_a_new_vulnerability_reports_the_new_one(h):
    names = [f"Locked finding {i}" for i in range(7)]
    first = h.scan([failure(n) for n in names])
    ws = first["workspace_id"]
    h.saboteur_calls.clear()
    second = h.scan([failure(n) for n in names] + [failure("Brand new vulnerability")], code="code v2")
    assert h.saboteur_calls[0]["max_scenarios"] >= 8                  # the model is not told to stop at seven
    reported = [f.failure_mode for f in second["failures"]]
    assert "Brand new vulnerability" in reported and len(reported) == 8
    assert second["new_scenarios"] == ["Brand new vulnerability"]
    assert h.states(ws)["Brand new vulnerability"] == "new"


# ── AC2: locked scores and expert adjustments ─────────────────────────────────

def test_changed_code_keeps_locked_scores_and_expert_adjustments(h):
    first = h.scan([failure("A"), failure("B")])
    ws = first["workspace_id"]
    db.save_adjustment(ws, "A", 3, 3, 3, "accepted risk after review")
    second = h.scan([failure("A"), failure("B")], code="code v2")
    scores = {r.failure_mode: (r.severity, r.occurrence, r.detection) for r in second["risks"]}
    assert scores["A"] == (3, 3, 3)                                    # expert adjustment overlays the locked score
    assert scores["B"] == (8, 5, 5)                                    # locked score from the first scan


# ── AC3: refuted locked finding becomes a fix candidate ───────────────────────

def test_a_locked_finding_missing_from_a_rescan_becomes_a_fix_candidate_not_dropped(h):
    first = h.scan([failure("Keeps appearing"), failure("Gets fixed")])
    ws = first["workspace_id"]
    second = h.scan([failure("Keeps appearing")], code="code v2 (fix landed)")
    assert h.states(ws) == {"Keeps appearing": "confirmed", "Gets fixed": "fix_candidate"}
    assert [c["failure_mode"] for c in second["fix_candidates"]] == ["Gets fixed"]
    assert second["lifecycle_changes"]["fix_candidates"] == ["Gets fixed"]
    stored = {r["failure_mode"]: (r["severity"], r["occurrence"], r["detection"]) for r in db.get_locked_scenarios(ws)}
    assert stored["Gets fixed"] == (8, 5, 5)                           # scores are kept for a possible regression


def test_the_model_is_told_that_fixed_findings_may_be_left_out_and_fix_candidates_are_not_demanded(h):
    first = h.scan([failure("Active"), failure("Fixed one"), failure("Candidate")])
    ws = first["workspace_id"]
    db.set_scenario_state(ws, "Fixed one", "fixed", actor="sam")
    db.set_scenario_state(ws, "Candidate", "fix_candidate")
    h.saboteur_calls.clear()
    h.scan([failure("Active")], code="code v2")
    assert h.saboteur_calls[0]["locked_names"] == ["Active"]
    assert sorted(h.saboteur_calls[0]["previous_names"]) == ["Candidate", "Fixed one"]    # anchors, reported only if present


def test_a_fix_candidate_that_reappears_goes_back_to_confirmed(h):
    first = h.scan([failure("Flaky"), failure("Other")])
    ws = first["workspace_id"]
    h.scan([failure("Other")], code="code v2")
    assert h.states(ws)["Flaky"] == "fix_candidate"
    h.scan([failure("Flaky"), failure("Other")], code="code v3")
    assert h.states(ws)["Flaky"] == "confirmed"


def test_the_saboteur_prompt_lets_fixed_findings_drop_out_and_does_not_count_locked_ones_against_the_cap(monkeypatch):
    import agents.saboteur as saboteur
    captured = {}

    def fake_call(prompt, max_tokens=4096):
        captured["prompt"] = prompt
        return "[]"

    monkeypatch.setattr(saboteur, "call_llm", fake_call)
    ctx = SystemContext(tiering={}, attack_surfaces=[], failure_domains=[])
    saboteur.run_saboteur("code", ctx, max_scenarios=14, locked_names=["Locked one"])
    prompt = captured["prompt"]
    assert "Locked one" in prompt and "no longer" in prompt.lower()
    assert "MUST reproduce ALL" not in prompt
    assert "do not count against" in prompt.lower()


# ── AC4: regression ───────────────────────────────────────────────────────────

def test_a_fixed_finding_that_returns_becomes_regressed_with_the_causing_scan(h):
    first = h.scan([failure("Comes back"), failure("Stays")])
    ws = first["workspace_id"]
    h.scan([failure("Stays")], code="code v2")
    db.set_scenario_state(ws, "Comes back", "fixed", actor="sam")
    third = h.scan([failure("Comes back"), failure("Stays")], code="code v3")
    assert h.states(ws)["Comes back"] == "regressed"
    assert third["lifecycle_changes"]["regressed"] == ["Comes back"]
    events = [e for e in db.list_finding_events(ws) if e["failure_mode"] == "Comes back"]
    assert [(e["from_state"], e["to_state"]) for e in events][-1] == ("fixed", "regressed")
    assert events[-1]["scan_id"] == third["db_scan_id"]


def test_a_new_finding_becomes_confirmed_when_the_next_scan_sees_it_again(h):
    first = h.scan([failure("Fresh")])
    ws = first["workspace_id"]
    assert h.states(ws) == {"Fresh": "new"}
    h.scan([failure("Fresh")], code="code v2")
    assert h.states(ws) == {"Fresh": "confirmed"}


# ── AC5: migration ────────────────────────────────────────────────────────────

def test_existing_registry_rows_migrate_with_their_locked_scores(h, tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.executescript("""
        CREATE TABLE workspaces (id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT NOT NULL, project TEXT NOT NULL,
            function TEXT, business_tier TEXT, user_type TEXT, business_context TEXT, customer_learning INTEGER DEFAULT 1,
            created_at TEXT NOT NULL, UNIQUE(customer, project));
        CREATE TABLE scenarios (id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL, first_fingerprint TEXT NOT NULL,
            failure_mode TEXT NOT NULL, attack_chain_json TEXT, severity INTEGER, occurrence INTEGER, detection INTEGER,
            rpn INTEGER, embedding BLOB, created_at TEXT NOT NULL, UNIQUE(workspace_id, failure_mode));
    """)
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO workspaces (customer, project, created_at) VALUES ('Shop', 'api', ?)", (now,))
    conn.execute("INSERT INTO scenarios (workspace_id, first_fingerprint, failure_mode, attack_chain_json, severity, occurrence,"
                 " detection, rpn, created_at) VALUES (1, 'fp0', 'Old locked finding', '[\"a\"]', 9, 6, 4, 216, ?)", (now,))
    conn.commit(); conn.close()
    monkeypatch.setattr(db, "_DB_PATH", old)

    rows = db.get_locked_scenarios(1)
    assert [(r["failure_mode"], r["severity"], r["occurrence"], r["detection"], r["state"]) for r in rows] == \
        [("Old locked finding", 9, 6, 4, "confirmed")]
    result = h.scan([failure("Old locked finding", "a.py:1 `danger(request.args['x'], shell=True)`")])
    assert (result["risks"][0].severity, result["risks"][0].occurrence, result["risks"][0].detection) == (9, 6, 4)
    row = db.get_locked_scenarios(1)[0]
    assert row["state"] == "confirmed" and row["identity_key"] == findings.finding_identity("a.py:1 `danger(request.args['x'], shell=True)`")   # learned


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def api(h):
    from api.main import app
    return TestClient(app, headers={"X-Requested-With": "fmea"})


def test_findings_api_lists_states_and_events_and_records_who_changed_them(h, api):
    first = h.scan([failure("Gets fixed"), failure("Stays")])
    ws = first["workspace_id"]
    h.scan([failure("Stays")], code="code v2")
    listed = {f["failure_mode"]: f for f in api.get(f"/api/workspace/{ws}/findings").json()["findings"]}
    assert listed["Gets fixed"]["state"] == "fix_candidate" and listed["Stays"]["state"] == "confirmed"
    r = api.post(f"/api/workspace/{ws}/findings/state", json={"failure_mode": "Gets fixed", "state": "fixed"})
    assert r.status_code == 200 and r.json()["state"] == "fixed"
    event = [e for e in api.get(f"/api/workspace/{ws}/findings").json()["events"] if e["failure_mode"] == "Gets fixed"][-1]
    assert (event["from_state"], event["to_state"], event["actor"]) == ("fix_candidate", "fixed", "test-admin")


def test_invalid_state_changes_are_refused(h, api):
    ws = h.scan([failure("A")])["workspace_id"]
    h.scan([failure("A")], code="code v2")                              # seen twice: confirmed
    assert api.post(f"/api/workspace/{ws}/findings/state", json={"failure_mode": "A", "state": "regressed"}).status_code == 422
    assert api.post(f"/api/workspace/{ws}/findings/state", json={"failure_mode": "A", "state": "confirmed"}).status_code == 409
    assert api.post(f"/api/workspace/{ws}/findings/state", json={"failure_mode": "Nope", "state": "fixed"}).status_code == 404
    assert api.post("/api/workspace/9999/findings/state", json={"failure_mode": "A", "state": "fixed"}).status_code == 404


def test_only_score_roles_may_change_a_finding_state(h, real_auth, monkeypatch):
    from api.main import app
    monkeypatch.setenv("FMEA_COOKIE_SECURE", "0")
    ws = h.scan([failure("A")])["workspace_id"]
    admin = TestClient(app, headers={"X-Requested-With": "fmea"})
    admin.post("/api/auth/setup", json={"username": "root", "password": "correct-horse-battery"})
    admin.post("/api/users", json={"username": "dana", "password": "correct-horse-battery", "role": "developer"})
    dev = TestClient(app, headers={"X-Requested-With": "fmea"})
    dev.post("/api/auth/login", json={"username": "dana", "password": "correct-horse-battery"})
    assert dev.get(f"/api/workspace/{ws}/findings").status_code == 200
    assert dev.post(f"/api/workspace/{ws}/findings/state", json={"failure_mode": "A", "state": "accepted"}).status_code == 403
    assert admin.post(f"/api/workspace/{ws}/findings/state", json={"failure_mode": "A", "state": "accepted"}).status_code == 200


# ── review follow-ups ─────────────────────────────────────────────────────────

Q = "src/db.py:7 `cursor.execute('SELECT * FROM orders WHERE id=' + order_id)`"


def test_a_cache_hit_applies_the_lifecycle_and_never_returns_stale_candidates(h, monkeypatch):
    import memory.workspace_store as ws_store
    first = h.scan([failure("F", Q), failure("Other")], code="code A")
    ws = first["workspace_id"]
    cached_a = {"failures": first["failures"], "risks": first["risks"], "fingerprint": "A", "from_cache": True,
                "fix_candidates": [{"failure_mode": "stale"}], "lifecycle_changes": {"new": ["stale"]}}
    h.scan([failure("Other")], code="code B (fix)")                      # F becomes a fix candidate
    db.set_scenario_state(ws, "F", "fixed", actor="sam")
    monkeypatch.setattr(ws_store, "get_cached_result", lambda *a, **k: dict(cached_a))
    reverted = pipeline.run_fmea("code A", workspace=WS)                 # reverting to code A: served from the cache
    assert h.states(ws)["F"] == "regressed"                              # the revert is a regression even without a rescan
    assert reverted["lifecycle_changes"]["regressed"] == ["F"] and reverted["fix_candidates"] == []
    assert "stale" not in json.dumps(reverted["fix_candidates"]) + json.dumps(reverted["lifecycle_changes"])


def test_showing_a_cached_new_finding_again_does_not_confirm_it(h, monkeypatch):
    import memory.workspace_store as ws_store
    first = h.scan([failure("Fresh")])
    ws = first["workspace_id"]
    monkeypatch.setattr(ws_store, "get_cached_result", lambda *a, **k: {"failures": first["failures"], "risks": first["risks"]})
    pipeline.run_fmea("code v1", workspace=WS)
    assert h.states(ws) == {"Fresh": "new"}


def test_a_decision_made_while_a_scan_runs_is_not_overwritten(h):
    first = h.scan([failure("A"), failure("B")])
    ws = first["workspace_id"]
    h.scan([failure("A"), failure("B")], code="v2")
    locked_before = db.get_locked_scenarios(ws)                          # the scan's snapshot: both confirmed
    db.set_scenario_state(ws, "B", "accepted", actor="sam")             # a person accepts B while the scan runs
    registry.record_scan_outcome(ws, 99, [failure("A")], locked_before)  # the scan did not see B
    assert h.states(ws)["B"] == "accepted"
    assert not [e for e in db.list_finding_events(ws) if e["scan_id"] == 99 and e["failure_mode"] == "B"]


def test_two_scans_recording_the_same_outcome_write_one_event(h):
    first = h.scan([failure("A"), failure("Gone")])
    ws = first["workspace_id"]
    h.scan([failure("A"), failure("Gone")], code="v2")
    snapshot = db.get_locked_scenarios(ws)
    registry.record_scan_outcome(ws, 5, [failure("A")], snapshot)
    registry.record_scan_outcome(ws, 6, [failure("A")], snapshot)       # a concurrent scan with the same snapshot
    flagged = [e for e in db.list_finding_events(ws) if e["failure_mode"] == "Gone" and e["to_state"] == "fix_candidate"]
    assert len(flagged) == 1


def test_a_failure_that_would_map_to_an_already_reported_finding_stays_separate(h):
    first = h.scan([failure("Injection", Q)])
    second = h.scan([failure("Injection", Q), failure("Different weakness, same line", Q)], code="v2")
    names = [f.failure_mode for f in second["failures"]]
    assert sorted(names) == ["Different weakness, same line", "Injection"]       # not two results named Injection


def test_ambiguous_identity_is_never_guessed(h):
    first = h.scan([failure("One", Q)])
    ws = first["workspace_id"]
    h.scan([failure("One", Q), failure("Two", Q)], code="v2")                    # same quote: the second gets no identity
    keys = [r["identity_key"] for r in db.get_locked_scenarios(ws)]
    assert keys.count(findings.finding_identity(Q)) == 1 and None in keys
    rows = [{"failure_mode": "X", "identity_key": findings.finding_identity(Q)},
            {"failure_mode": "Y", "identity_key": findings.finding_identity(Q)}]
    assert registry.find_by_identity(failure("Z", Q), rows) is None


def test_history_has_a_birth_event_and_unlocking_leaves_a_record(h):
    first = h.scan([failure("A")])
    ws = first["workspace_id"]
    assert [(e["from_state"], e["to_state"]) for e in db.list_finding_events(ws)] == [(None, "new")]
    db.delete_scenario(ws, "A")
    assert [(e["from_state"], e["to_state"]) for e in db.list_finding_events(ws)][-1] == ("new", "removed")
