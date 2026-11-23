"""
B-053: the Remediate button's two routes. One asks the model for a fix to one chosen action of one finding;
the other records what a person decided about it (accept, edit, reject) in the audit trail. The model is faked.
"""

import json

import pytest
from fastapi.testclient import TestClient

import memory.db as db
from core.models import Action, FailureMode, RemediationPlan

CODE = "def get_user(user_input):\n    query = 'SELECT * FROM users WHERE id = %s' % user_input\n    return cursor.execute(query)\n"
REPLY = json.dumps({"code_diff": "--- original\n+++ patched\n-x\n+y", "test_code": "def test_x():\n    assert True",
                    "test_description": "checks the fix", "patched_snippet": "def get_user(user_input):\n    return 1\n"})


def _plan():
    return RemediationPlan(failure_mode="SQL Injection",
                           corrective=[Action(id="c1", title="Use parameterised queries", kind="code_fix", target="db.py"),
                                       Action(id="c2", title="Validate input length", kind="code_fix", target="api.py")],
                           preventive=[Action(id="p1", title="Add a static analysis rule", kind="monitoring")])


@pytest.fixture
def stored_scan(monkeypatch, tmp_path):
    from api.store import scan_store
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "t.db")
    failure = FailureMode(failure_mode="SQL Injection", attack_chain=["a"], business_impact="b", blast_radius="c",
                          trigger="t", evidence="cursor.execute(query)")
    scan_store[9001] = {"result": {"failures": [failure.model_dump()], "risks": [], "remediations": [_plan().model_dump()]},
                        "code": CODE, "workspace": None}
    yield 9001
    scan_store.pop(9001, None)


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app, headers={"x-requested-with": "fmea"})


def _prompts(monkeypatch):
    seen = []
    monkeypatch.setattr("agents.remediator.call_llm", lambda prompt, max_tokens=0: seen.append(prompt) or REPLY)
    return seen


def test_a_fix_is_proposed_for_the_chosen_action(client, stored_scan, monkeypatch):
    seen = _prompts(monkeypatch)
    r = client.post("/api/remediate/finding", json={"scan_id": stored_scan, "failure_mode": "SQL Injection", "action_id": "c2"})
    assert r.status_code == 200
    body = r.json()
    assert body["code_diff"].startswith("--- original") and "def test_x" in body["test_code"] and "def get_user" in body["patched_snippet"]
    assert "Validate input length" in seen[0] and "Use parameterised queries" not in seen[0]      # the chosen action, not the top one


def test_a_preventive_action_can_be_chosen_too(client, stored_scan, monkeypatch):
    seen = _prompts(monkeypatch)
    assert client.post("/api/remediate/finding", json={"scan_id": stored_scan, "failure_mode": "SQL Injection", "action_id": "p1"}).status_code == 200
    assert "Add a static analysis rule" in seen[0]


def test_missing_scan_finding_or_action_is_a_plain_404(client, stored_scan, monkeypatch):
    _prompts(monkeypatch)
    for body in ({"scan_id": 1, "failure_mode": "SQL Injection", "action_id": "c1"},
                 {"scan_id": stored_scan, "failure_mode": "Nope", "action_id": "c1"},
                 {"scan_id": stored_scan, "failure_mode": "SQL Injection", "action_id": "zzz"}):
        r = client.post("/api/remediate/finding", json=body)
        assert r.status_code == 404 and "Traceback" not in r.text


def test_a_provider_failure_is_a_plain_message(client, stored_scan, monkeypatch):
    def boom(prompt, max_tokens=0):
        raise ValueError("/home/secret/path exploded")
    monkeypatch.setattr("agents.remediator.call_llm", boom)
    r = client.post("/api/remediate/finding", json={"scan_id": stored_scan, "failure_mode": "SQL Injection", "action_id": "c1"})
    assert r.status_code == 502 and "secret" not in r.text and "failed" in r.json()["detail"].lower()


@pytest.mark.parametrize("decision", ["accepted", "edited", "rejected"])
def test_a_decision_is_recorded_in_the_audit_trail(client, stored_scan, decision):
    r = client.post("/api/remediate/decision", json={"scan_id": stored_scan, "failure_mode": "SQL Injection", "action_id": "c1", "decision": decision})
    assert r.status_code == 200 and r.json()["decision"] == decision
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT action, detail FROM audit_events WHERE action = ?", (f"fix_{decision}",)).fetchall()
    finally:
        conn.close()
    assert rows and "SQL Injection" in rows[-1][1] and "c1" in rows[-1][1]


def test_an_unknown_decision_is_refused(client, stored_scan):
    r = client.post("/api/remediate/decision", json={"scan_id": stored_scan, "failure_mode": "SQL Injection", "action_id": "c1", "decision": "merge"})
    assert r.status_code == 422


def test_both_routes_need_the_scan_permission():
    from api.policy import POLICY, ROLE_PERMISSIONS
    assert POLICY[("POST", "/api/remediate/finding")] == "scan" and POLICY[("POST", "/api/remediate/decision")] == "scan"
    assert "scan" not in ROLE_PERMISSIONS["viewer"] and "scan" not in ROLE_PERMISSIONS["risk_manager"]
