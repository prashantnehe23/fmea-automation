"""
B-053 and B-056 (ADR-033): the two Remediate routes and the module behind them.

A fix is proposed from the stored scan snapshot (findings, fix plans and source files in the database), not from server
memory. The model is shown the files the finding cites and returns edits; the server validates and applies them and builds
the unified diff itself. The decision route rebuilds the diff from the person's final text and audits files and a hash.
The model is faked throughout.
"""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import memory.db as db
from core import fix_proposal as fp
from core.models import Action, FailureMode, PathStep, RemediationPlan

PUBLIC = ("import requests\nfrom flask import Flask, request\n\napp = Flask(__name__)\n\n@app.route('/preview')\n"
          "def preview():\n    url = request.args['url']\n    r = requests.get(url, timeout=5)\n    return {'title': r.text[:200]}\n")
ADMIN = ("from flask import Flask\n\nadmin = Flask(__name__)\n\n@admin.route('/wipe', methods=['POST'])\n"
         "def wipe():\n    return {'wiped': True}\n")
OTHER = "def unrelated():\n    return 1\n"
FILES = {"public.py": PUBLIC, "internal_admin.py": ADMIN, "other.py": OTHER}
NAME = "SSRF from /preview reaches the admin service"


def _failure(**kw):
    base = dict(failure_mode=NAME, attack_chain=["a"], business_impact="b", blast_radius="c", trigger="t",
                evidence="public.py:9 `r = requests.get(url, timeout=5)`",
                exploit_path=[PathStep(file="public.py", lines="9", action="fetches any url", quote="r = requests.get(url, timeout=5)"),
                              PathStep(file="internal_admin.py", lines="7", action="no auth", quote="return {'wiped': True}")])
    base.update(kw)
    return FailureMode(**base)


def _plan(name=NAME):
    return RemediationPlan(failure_mode=name,
                           corrective=[Action(id="c1", title="Restrict fetch destinations", kind="code_fix", target="public.py"),
                                       Action(id="c2", title="Require a token on the admin route", kind="code_fix", target="internal_admin.py")],
                           preventive=[Action(id="p1", title="Add a static analysis rule", kind="monitoring")])


def _reply(edits=None, **kw):
    body = {"edits": edits if edits is not None else [
        {"file": "public.py", "start_line": 9, "end_line": 9, "replacement": "    r = requests.get(url, timeout=5) if url.startswith('https://example.com/') else None"}],
        "test_code": "def test_x():\n    assert True", "test_description": "checks it", "reason": "limits where the preview may fetch"}
    body.update(kw)
    return json.dumps(body)


@pytest.fixture
def stored(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "t.db")
    ws = SimpleNamespace(customer="Shop", project="api", function="", business_tier="Tier 1", user_type="external_customers",
                         business_context="", customer_learning=True)
    wid = db.upsert_workspace(ws)
    result = {"failures": [_failure().model_dump()], "remediations": [_plan().model_dump()], "workspace_id": wid, "db_scan_id": 77}
    db.save_scan_snapshot(wid, 77, "fp-1", result, dict(FILES))
    return SimpleNamespace(workspace_id=wid, scan_id=77, db=db)


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app, headers={"x-requested-with": "fmea"})


@pytest.fixture
def prompts(monkeypatch):
    seen = []

    def fake(prompt, max_tokens=0):
        seen.append(prompt)
        return _reply()
    monkeypatch.setattr(fp, "call_llm", fake)
    return seen


def _body(stored, **kw):
    base = {"workspace_id": stored.workspace_id, "scan_id": stored.scan_id, "failure_mode": NAME, "action_id": "c1"}
    base.update(kw)
    return base


# ── A: the stored snapshot is the source of truth ─────────────────────────────

def test_a_fix_is_proposed_from_the_database_with_nothing_in_server_memory(client, stored, prompts):
    from api.store import scan_store
    scan_store.clear()                                               # a restarted server
    r = client.post("/api/remediate/finding", json=_body(stored))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edits"][0]["file"] == "public.py" and body["edits"][0]["original"].strip().startswith("r = requests.get")
    assert body["diff"].startswith("--- a/public.py\n+++ b/public.py") and "example.com" in body["diff"]
    assert body["test_code"].startswith("def test_x") and body["context"] == "cited" and body["dropped"] == []


def test_the_snapshot_is_matched_on_both_ids_exactly(client, stored, prompts):
    other = db.upsert_workspace(SimpleNamespace(customer="Other", project="app", function="", business_tier="Tier 1",
                                                user_type="external_customers", business_context="", customer_learning=True))
    for body in (_body(stored, scan_id=999), _body(stored, workspace_id=other), _body(stored, workspace_id=other, scan_id=999)):
        r = client.post("/api/remediate/finding", json=body)
        assert r.status_code == 404 and "Traceback" not in r.text
    assert prompts == []                                             # no model call for another project's or an unknown scan


def test_a_scan_whose_sources_are_not_stored_is_a_409_without_a_model_call(client, monkeypatch, tmp_path, prompts):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "t2.db")
    wid = db.upsert_workspace(SimpleNamespace(customer="N", project="p", function="", business_tier="Tier 1", user_type="external_customers",
                                              business_context="", customer_learning=True))
    db.save_scan_snapshot(wid, 5, "fp", {"failures": [_failure().model_dump()], "remediations": [_plan().model_dump()]}, {})
    r = client.post("/api/remediate/finding", json={"workspace_id": wid, "scan_id": 5, "failure_mode": NAME, "action_id": "c1"})
    assert r.status_code == 409 and "source" in r.json()["detail"].lower() and "scan" in r.json()["detail"].lower()
    assert prompts == []


def test_missing_finding_or_action_is_a_plain_404(client, stored, prompts):
    for body in (_body(stored, failure_mode="Nope"), _body(stored, action_id="zzz")):
        r = client.post("/api/remediate/finding", json=body)
        assert r.status_code == 404 and "Traceback" not in r.text
    assert prompts == []


def test_a_plan_with_a_different_name_is_found_by_position(client, stored, prompts, monkeypatch):
    result = {"failures": [_failure().model_dump()], "remediations": [_plan("Another name for it").model_dump()]}
    db.save_scan_snapshot(stored.workspace_id, 78, "fp-2", result, dict(FILES))
    r = client.post("/api/remediate/finding", json=_body(stored, scan_id=78))
    assert r.status_code == 200 and "Restrict fetch destinations" in prompts[0]


# ── B: the model is shown the code the finding cites, and the chosen action ──

def test_the_prompt_has_the_cited_files_with_line_numbers_and_the_chosen_action(client, stored, prompts):
    client.post("/api/remediate/finding", json=_body(stored, action_id="c2"))
    prompt = prompts[0]
    assert "public.py" in prompt and "internal_admin.py" in prompt and "other.py" not in prompt
    assert "9| " in prompt and "Require a token on the admin route" in prompt and "Restrict fetch destinations" not in prompt


def test_a_finding_that_cites_only_evidence_uses_the_evidence_file():
    files, label = fp.pick_context(_failure(exploit_path=[]), FILES)
    assert list(files) == ["public.py"] and label == "cited"


def test_nothing_cited_falls_back_to_a_keyword_guess_and_says_so():
    files, label = fp.pick_context(_failure(failure_mode="Unsafe fetch", exploit_path=[], evidence="", trigger="the preview handler fetches whatever it is given"), FILES)
    assert label == "guess" and "public.py" in files


def test_at_most_three_files_are_shown():
    many = {f"f{i}.py": f"def f{i}():\n    return {i}\n" for i in range(6)}
    path = [PathStep(file=f"f{i}.py", lines="1", action="x", quote="def") for i in range(6)]
    files, _ = fp.pick_context(_failure(exploit_path=path, evidence=""), many)
    assert len(files) == 3


# ── C: edits are validated and applied by the server, the diff is built from real text ──

def test_edits_outside_the_shown_files_or_lines_or_overlapping_are_dropped_with_a_reason():
    shown = {"public.py": PUBLIC}
    edits = [{"file": "public.py", "start_line": 9, "end_line": 9, "replacement": "    pass"},
             {"file": "other.py", "start_line": 1, "end_line": 1, "replacement": "x"},          # not shown
             {"file": "public.py", "start_line": 90, "end_line": 91, "replacement": "x"},        # outside the file
             {"file": "public.py", "start_line": 9, "end_line": 10, "replacement": "y"}]         # overlaps the first
    applied, dropped = fp.validate_edits(edits, shown)
    assert [e["start_line"] for e in applied] == [9] and len(dropped) == 3
    assert any("not shown" in d["reason"] for d in dropped) and any("outside" in d["reason"] for d in dropped) and any("overlap" in d["reason"] for d in dropped)


def test_edits_are_applied_bottom_up_and_an_insertion_is_possible():
    shown = {"a.py": "one\ntwo\nthree\n"}
    applied, _ = fp.validate_edits([{"file": "a.py", "start_line": 1, "end_line": 1, "replacement": "ONE"},
                                    {"file": "a.py", "start_line": 3, "end_line": 2, "replacement": "inserted"}], shown)
    assert fp.apply_edits(applied, shown)["a.py"] == "ONE\ntwo\ninserted\nthree\n"


def test_the_diff_applies_with_git_apply(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    shown = {"public.py": PUBLIC}
    applied, _ = fp.validate_edits([{"file": "public.py", "start_line": 9, "end_line": 9, "replacement": "    r = None"}], shown)
    diff = fp.build_diff(shown, fp.apply_edits(applied, shown))
    (tmp_path / "public.py").write_text(PUBLIC, encoding="utf-8", newline="\n")
    (tmp_path / "p.diff").write_text(diff, encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    out = subprocess.run(["git", "apply", "--check", "p.diff"], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_a_changed_python_file_that_no_longer_parses_is_flagged_not_hidden(client, stored, monkeypatch):
    bad = _reply(edits=[{"file": "public.py", "start_line": 9, "end_line": 9, "replacement": "    r = ((("}])
    monkeypatch.setattr(fp, "call_llm", lambda prompt, max_tokens=0: bad)
    body = client.post("/api/remediate/finding", json=_body(stored)).json()
    assert body["parse_errors"] == ["public.py"] and body["edits"]


def test_a_reply_without_usable_edits_is_a_plain_error(client, stored, monkeypatch):
    monkeypatch.setattr(fp, "call_llm", lambda prompt, max_tokens=0: _reply(edits=[{"file": "other.py", "start_line": 1, "end_line": 1, "replacement": "x"}]))
    r = client.post("/api/remediate/finding", json=_body(stored))
    assert r.status_code == 502 and "usable" in r.json()["detail"].lower()


def test_a_provider_failure_is_a_plain_message(client, stored, monkeypatch):
    def boom(prompt, max_tokens=0):
        raise ValueError("/home/secret/path exploded")
    monkeypatch.setattr(fp, "call_llm", boom)
    r = client.post("/api/remediate/finding", json=_body(stored))
    assert r.status_code == 502 and "secret" not in r.text and "failed" in r.json()["detail"].lower()


# ── the person's decision ──────────────────────────────────────────────────────

def _audit(action):
    conn = db.get_db()
    try:
        return conn.execute("SELECT detail FROM audit_events WHERE action = ?", (action,)).fetchall()
    finally:
        conn.close()


def test_an_edited_fix_gets_a_rebuilt_diff_and_the_audit_names_files_and_a_hash_but_no_code(client, stored):
    edits = [{"file": "public.py", "start_line": 9, "end_line": 9, "replacement": "    r = None  # SECRET-MARKER-FOR-TEST"}]
    r = client.post("/api/remediate/decision", json={**_body(stored), "decision": "edited", "edits": edits})
    assert r.status_code == 200
    body = r.json()
    assert "SECRET-MARKER-FOR-TEST" in body["diff"] and body["decision"] == "edited" and len(body["diff_sha256"]) == 64
    detail = _audit("fix_edited")[-1][0]
    assert "public.py" in detail and body["diff_sha256"][:16] in detail and "SECRET-MARKER-FOR-TEST" not in detail and "\n" not in detail


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_every_decision_is_recorded(client, stored, decision):
    edits = [] if decision == "rejected" else [{"file": "public.py", "start_line": 9, "end_line": 9, "replacement": "    r = None"}]
    r = client.post("/api/remediate/decision", json={**_body(stored), "decision": decision, "edits": edits})
    assert r.status_code == 200 and _audit(f"fix_{decision}")


def test_an_unknown_decision_or_a_scan_that_is_not_stored_is_refused(client, stored):
    assert client.post("/api/remediate/decision", json={**_body(stored), "decision": "merge", "edits": []}).status_code == 422
    assert client.post("/api/remediate/decision", json={**_body(stored, scan_id=1), "decision": "accepted", "edits": []}).status_code == 404


def test_a_decision_with_edits_that_do_not_fit_the_stored_files_is_refused(client, stored):
    edits = [{"file": "public.py", "start_line": 500, "end_line": 501, "replacement": "x"}]
    assert client.post("/api/remediate/decision", json={**_body(stored), "decision": "accepted", "edits": edits}).status_code == 422


def test_both_routes_need_the_scan_permission():
    from api.policy import POLICY, ROLE_PERMISSIONS
    assert POLICY[("POST", "/api/remediate/finding")] == "scan" and POLICY[("POST", "/api/remediate/decision")] == "scan"
    assert "scan" not in ROLE_PERMISSIONS["viewer"] and "scan" not in ROLE_PERMISSIONS["risk_manager"]


# ── independent review of B-056: edge cases of applying edits ─────────────────

def _apply(text, edits):
    shown = {"a.py": text}
    applied, dropped = fp.validate_edits(edits, shown)
    assert not dropped, dropped
    return fp.apply_edits(applied, shown)["a.py"]


@pytest.mark.parametrize("order", ["insert-first", "replace-first"])
def test_an_insertion_and_a_replacement_at_the_same_line_both_survive_whatever_the_order(order):
    ins = {"file": "a.py", "start_line": 2, "end_line": 1, "replacement": "INS"}
    rep_ = {"file": "a.py", "start_line": 2, "end_line": 2, "replacement": "REP"}
    edits = [ins, rep_] if order == "insert-first" else [rep_, ins]
    assert _apply("l1\nl2\nl3\n", edits) == "l1\nINS\nREP\nl3\n"


def test_an_insertion_after_a_last_line_without_a_line_ending_starts_a_new_line():
    out = _apply("l1\nl2", [{"file": "a.py", "start_line": 3, "end_line": 2, "replacement": "INS"}])
    assert out == "l1\nl2\nINS"                          # no trailing newline stays as it was


def test_crlf_files_keep_crlf_and_a_single_blank_line_is_possible():
    out = _apply("l1\r\nl2\r\nl3\r\n", [{"file": "a.py", "start_line": 2, "end_line": 2, "replacement": "A\nB"}])
    assert out == "l1\r\nA\r\nB\r\nl3\r\n"
    assert _apply("l1\nl2\n", [{"file": "a.py", "start_line": 2, "end_line": 2, "replacement": "\n"}]) == "l1\n\n"


def test_lines_are_counted_the_way_git_counts_them():
    text = "l1\x0cstill l1\nl2\n"                          # a form feed does not end a line
    assert len(fp._split(text)) == 2
    assert _apply(text, [{"file": "a.py", "start_line": 2, "end_line": 2, "replacement": "NEW"}]) == "l1\x0cstill l1\nNEW\n"


def test_edits_outside_the_lines_the_model_was_shown_are_dropped():
    big = "".join(f"line {i}\n" for i in range(1, 6000))          # over the size limit: only windows around cited lines are shown
    failure = _failure(exploit_path=[PathStep(file="big.py", lines="3000", action="x", quote="line 3000")], evidence="")
    shown = {"big.py": big}
    spans = {"big.py": fp.view_spans("big.py", big, failure)}
    assert spans["big.py"] == [(2920, 3080)]
    applied, dropped = fp.validate_edits([{"file": "big.py", "start_line": 3001, "end_line": 3001, "replacement": "x"},
                                          {"file": "big.py", "start_line": 10, "end_line": 10, "replacement": "y"}], shown, spans)
    assert [e["start_line"] for e in applied] == [3001] and "not shown" in dropped[0]["reason"]


def test_a_path_that_starts_with_a_dot_is_still_found_and_a_path_with_a_newline_is_never_shown():
    files = {".github/ci.yml": "a: 1\n", "ok.py": "x = 1\n", "bad\nname.py": "y = 2\n"}
    assert fp._resolve(".github/ci.yml", files) == ".github/ci.yml" and fp._resolve("./ok.py", files) == "ok.py"
    shown, _ = fp.pick_context(_failure(exploit_path=[PathStep(file="bad\nname.py", lines="1", action="x", quote="y")], evidence="ok.py:1"), files)
    assert "bad\nname.py" not in shown


def test_edit_numbers_must_be_real_integers_and_there_are_at_most_twenty_edits():
    shown = {"a.py": "l1\nl2\n"}
    applied, dropped = fp.validate_edits([{"file": "a.py", "start_line": True, "end_line": 1, "replacement": "x"},
                                          {"file": "a.py", "start_line": 1.5, "end_line": 1, "replacement": "x"}], shown)
    assert applied == [] and len(dropped) == 2
    many = [{"file": "a.py", "start_line": 1, "end_line": 1, "replacement": "x"}] * 50
    assert len(fp.validate_edits(many, shown)[0]) <= 1 and fp.MAX_EDITS == 20


def test_an_accepted_or_edited_decision_without_edits_is_refused_but_a_rejection_needs_none(client, stored):
    for decision in ("accepted", "edited"):
        assert client.post("/api/remediate/decision", json={**_body(stored), "decision": decision, "edits": []}).status_code == 422
    assert client.post("/api/remediate/decision", json={**_body(stored), "decision": "rejected", "edits": []}).status_code == 200


def test_propose_and_decide_show_the_same_files(client, stored, prompts):
    proposed, _ = fp.pick_context(_failure(), FILES)
    again, _ = fp.pick_context(_failure(), dict(reversed(list(FILES.items()))))      # the order the database returns files in must not matter
    assert list(proposed) == list(again)
