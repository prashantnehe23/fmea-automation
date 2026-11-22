"""
B-012 — pull-request check (ADR-029: invoked from CI, verdict and comment returned by the API).

  AC  a pull request that introduces a catastrophic finding fails, with a comment naming file and line
  AC  a pull request with no new or regressed findings passes and comments nothing
  AC  unchanged findings are not reported again (identity from B-031)
  AC  the check never exceeds its USD budget; reaching it passes with a "budget reached" notice
  (A run on a real test repository with a real model needs a key: see the backlog.)
"""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import core.llm as llm
import memory.db as db
import workflows.fmea_pipeline as pipeline
from core import auth, budget, pr_check
from core.scan_scope import ScopeEntry, classify_tree, plan_batches
from test_finding_lifecycle import Harness, failure

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/acme/shop"
SHA = "a1b2c3d4e5f6"
CSRF = {"X-Requested-With": "fmea"}
EVIDENCE = "src/payments/charge.py:42 `db.execute('UPDATE accounts SET bal=' + amount + ' WHERE id=' + uid)`"


class PrHarness(Harness):
    """Scripted agents plus a baseline project whose repository is acme/shop."""

    def __init__(self, monkeypatch, tmp_path):
        super().__init__(monkeypatch, tmp_path)
        self.portfolio = db.create_portfolio("Shop")
        self.project = db.create_project(self.portfolio["id"], "api", REPO)
        self.tree = classify_tree([("src/payments/charge.py", 900), ("src/app.py", 900), ("README.md", 100)])
        monkeypatch.setattr(pr_check, "list_repo", lambda url: (NS(owner="acme", repo="shop", branch=SHA), self.tree, "README.md"))
        monkeypatch.setattr(pr_check, "fetch_contents", lambda ref, paths: ({p: "x = 1\n" for p in paths}, {}))
        self.changes = {"src/payments/charge.py": None}                         # None: the whole file counts as changed
        monkeypatch.setattr(pr_check, "fetch_pr_changes", lambda owner, repo, number: self.changes)
        self.scores: dict[str, tuple[int, int, int]] = {}

    def _score(self, failures, controls, context, business_context="", locked_rpn=None):
        from core.models import RiskScore
        out = []
        for f in failures:
            row = (locked_rpn or {}).get(f.failure_mode)
            s, o, d = (row["severity"], row["occurrence"], row["detection"]) if row else self.scores.get(f.failure_mode, (6, 5, 5))
            out.append(RiskScore(failure_mode=f.failure_mode, severity=s, occurrence=o, detection=d, rpn=s * o * d,
                                 priority="High", justification="j", severity_rationale="", occurrence_rationale="",
                                 detection_rationale=""))
        return out

    def baseline(self, failures):
        """A scan of the default branch: what the registry knows, and the stored snapshot the scan route saves."""
        result = self.scan(failures)
        db.save_scan_snapshot(result["workspace_id"], None, "baseline-fp",
                              {"failures": [f.model_dump() for f in result["failures"]], "risks": []}, {})
        return result["workspace_id"]

    def check(self, failures, **kw):
        self.next_failures = failures
        params = dict(owner="acme", repo="shop", head_sha=SHA, pr_number=7)
        params.update(kw)
        return pr_check.run_pr_check(**params)

    def registry(self, ws):
        conn = sqlite3.connect(db._DB_PATH)
        rows = conn.execute("SELECT failure_mode, state FROM scenarios WHERE workspace_id=? ORDER BY id", (ws,)).fetchall()
        events = conn.execute("SELECT COUNT(*) FROM finding_events WHERE workspace_id=?", (ws,)).fetchone()[0]
        scans = conn.execute("SELECT COUNT(*) FROM scans WHERE workspace_id=?", (ws,)).fetchone()[0]
        conn.close()
        return rows, events, scans


@pytest.fixture
def ph(monkeypatch, tmp_path):
    import core.settings as settings
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    return PrHarness(monkeypatch, tmp_path)


# ── the verdict ───────────────────────────────────────────────────────────────

def test_a_pull_request_that_introduces_a_catastrophic_finding_fails_and_names_file_and_line(ph):
    ph.baseline([failure("Existing finding")])
    ph.scores["Balance update by string concatenation"] = (9, 6, 6)
    out = ph.check([failure("Existing finding"), failure("Balance update by string concatenation", EVIDENCE)])
    assert out["verdict"] == "fail"
    new = out["new"][0]
    assert (new["failure_mode"], new["severity"], new["file"], new["line"]) == ("Balance update by string concatenation", 9, "src/payments/charge.py", 42)
    assert f"https://github.com/acme/shop/blob/{SHA}/src/payments/charge.py#L42" in out["comment_markdown"]
    assert "src/payments/charge.py:42" in out["comment_markdown"] and "Balance update" in out["comment_markdown"]


def test_a_pull_request_with_no_new_or_regressed_findings_passes_and_comments_nothing(ph):
    ph.baseline([failure("A"), failure("B")])
    out = ph.check([failure("A"), failure("B")])
    assert out["verdict"] == "pass" and out["new"] == [] and out["regressed"] == []
    assert out["comment_markdown"] == "" and "no new or regressed" in out["summary"].lower()


def test_unchanged_findings_are_not_reported_again_even_when_renamed_or_moved(ph):
    quote = "src/old.py:3 `os.system('ping ' + request.args['host'])`"
    ph.baseline([failure("Command injection in ping", quote)])
    moved = "src/net/tools.py:11 `os.system('ping ' + request.args['host'])`"
    out = ph.check([failure("Unsafe shell call", moved)])
    assert out["new"] == [] and out["verdict"] == "pass"


def test_a_new_finding_below_the_threshold_is_listed_but_does_not_fail(ph):
    ph.baseline([failure("Existing")])
    ph.scores["Minor issue"] = (5, 5, 5)
    out = ph.check([failure("Existing"), failure("Minor issue", "src/payments/charge.py:3 `print(secret_value_here)`")])
    assert out["verdict"] == "pass" and [n["failure_mode"] for n in out["new"]] == ["Minor issue"]
    assert "Minor issue" in out["comment_markdown"]


def test_a_regressed_catastrophic_finding_fails(ph):
    ph.scores["Was fixed"] = (9, 6, 6)                                         # catastrophic when it was first found
    ws = ph.baseline([failure("Was fixed", EVIDENCE), failure("Other")])
    ph.scan([failure("Other")], code="code v2")
    db.set_scenario_state(ws, "Was fixed", "fixed", actor="sam")
    out = ph.check([failure("Was fixed", EVIDENCE), failure("Other")])
    assert [r["failure_mode"] for r in out["regressed"]] == ["Was fixed"] and out["new"] == []
    assert out["regressed"][0]["severity"] == 9 and out["verdict"] == "fail"
    assert "came back after being fixed" in out["comment_markdown"]


def test_the_failure_threshold_is_configurable_per_project(ph):
    ph.baseline([failure("Existing")])
    ph.scores["Serious"] = (9, 6, 6)
    db.set_pr_check_config(ph.project["id"], fail_severity=10)
    out = ph.check([failure("Existing"), failure("Serious", EVIDENCE)])
    assert out["verdict"] == "pass" and out["new"][0]["severity"] == 9


def test_without_a_baseline_the_check_passes_with_a_notice(ph):
    ph.scores["Anything"] = (9, 6, 6)
    out = ph.check([failure("Anything", EVIDENCE)])
    assert out["verdict"] == "pass" and "baseline" in out["summary"].lower() and out["new"] == []


def test_a_disabled_project_is_skipped_with_a_notice(ph):
    ph.baseline([failure("A")])
    db.set_pr_check_config(ph.project["id"], enabled=False)
    ph.saboteur_calls.clear()
    out = ph.check([failure("B", EVIDENCE)])
    assert out["verdict"] == "pass" and "disabled" in out["summary"].lower() and ph.saboteur_calls == []      # nothing was scanned


def test_an_unknown_repository_is_a_plain_error(ph):
    with pytest.raises(pr_check.PrCheckError) as exc:
        pr_check.run_pr_check(owner="nobody", repo="nothing", head_sha=SHA)
    assert "No project is linked" in str(exc.value)


# ── nothing on the default branch's record changes ────────────────────────────

def test_a_check_leaves_the_registry_history_and_scan_record_untouched(ph):
    ws = ph.baseline([failure("A"), failure("Gone")])
    ph.scores["Fresh"] = (9, 6, 6)
    before = ph.registry(ws)
    ph.check([failure("A"), failure("Fresh", EVIDENCE)])                      # "Gone" is missing, "Fresh" is new
    assert ph.registry(ws) == before


def test_a_check_runs_a_single_quick_pass_with_no_cap(ph):
    ph.baseline([failure("A")])
    ph.saboteur_calls.clear()
    ph.check([failure("A")])
    assert len(ph.saboteur_calls) == 1 and ph.saboteur_calls[0].get("part") is None and ph.saboteur_calls[0]["max_scenarios"] is None


def test_files_changed_by_the_pull_request_are_scanned_first(monkeypatch):
    entries = [ScopeEntry(f"src/mod{i:02d}.py", True, "code file", "code", 40_000) for i in range(20)]
    entries.append(ScopeEntry("src/zz_changed.py", True, "code file", "code", 40_000))
    batches, _ = plan_batches(entries, budget=300_000, max_batches=1, boost={"src/zz_changed.py"})
    assert "src/zz_changed.py" in [e.path for e in batches[0]]
    plain, _ = plan_batches(entries, budget=300_000, max_batches=1)
    assert "src/zz_changed.py" not in [e.path for e in plain[0]]


# ── the budget ────────────────────────────────────────────────────────────────

def test_the_spend_limit_stops_the_next_call_and_the_overshoot_is_at_most_one_call(monkeypatch):
    monkeypatch.setattr(llm, "get_model_name", lambda: "gpt-5.1")
    with budget.spend_limit(0.50) as tracker:
        llm._add_usage(calls=1, prompt=100_000, completion=1_000)             # about $0.14
        assert not tracker.reached
        with pytest.raises(budget.BudgetReached):
            llm._add_usage(calls=1, prompt=1_000_000, completion=1_000)       # this call crosses the limit
        assert tracker.reached and tracker.spent_usd >= 0.50
        with pytest.raises(budget.BudgetReached):
            llm._get_client("openai")                                         # no further call is started


def test_without_a_limit_nothing_changes(monkeypatch):
    monkeypatch.setattr(llm, "get_model_name", lambda: "gpt-5.1")
    llm.reset_call_count()
    llm._add_usage(calls=1, prompt=50_000_000, completion=1_000_000)         # no exception: no limit set


def test_reaching_the_budget_passes_with_a_budget_reached_notice(ph, monkeypatch):
    ph.baseline([failure("A")])
    monkeypatch.setattr(llm, "get_model_name", lambda: "gpt-5.1")

    def costly_surveyor(code, business_context=""):
        llm._add_usage(calls=1, prompt=4_000_000, completion=10_000)         # about $5
        from core.models import SystemContext
        return SystemContext(tiering={}, attack_surfaces=[], failure_domains=[])

    monkeypatch.setattr(pipeline, "run_surveyor", costly_surveyor)
    out = ph.check([failure("Never reached", EVIDENCE)], budget_usd=0.25)
    assert out["verdict"] == "pass" and out["budget_reached"] is True and out["new"] == []
    assert "budget" in out["summary"].lower() and "budget" in out["comment_markdown"].lower()
    assert out["cost_usd"] >= 0.25 and out["budget_usd"] == 0.25


def test_a_check_inside_its_budget_reports_cost_and_no_notice(ph):
    ph.baseline([failure("A")])
    out = ph.check([failure("A")], budget_usd=0.5)
    assert out["budget_reached"] is False and out["budget_usd"] == 0.5 and out["cost_usd"] >= 0


def test_a_request_can_lower_the_projects_budget_but_never_raise_it(ph):
    ph.baseline([failure("A")])
    db.set_pr_check_config(ph.project["id"], budget_usd=1.0)
    assert ph.check([failure("A")], budget_usd=50.0)["budget_usd"] == 1.0
    assert ph.check([failure("A")], budget_usd=0.25)["budget_usd"] == 0.25
    assert ph.check([failure("A")])["budget_usd"] == 1.0


# ── the API ───────────────────────────────────────────────────────────────────

@pytest.fixture
def api(ph, real_auth, monkeypatch):
    from api.main import app
    monkeypatch.setenv("FMEA_COOKIE_SECURE", "0")
    admin = TestClient(app, headers=CSRF)
    admin.post("/api/auth/setup", json={"username": "root", "password": "correct-horse-battery"})
    ph.admin = admin
    return admin


def make_token(admin, name="github-actions"):
    r = admin.post("/api/tokens", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def test_a_token_authenticates_the_check_and_nothing_else(ph, api):
    from api.main import app
    ph.baseline([failure("A")])
    token = make_token(api)
    ci = TestClient(app)                                                       # no cookie, no CSRF header
    ph.next_failures = [failure("A")]
    r = ci.post("/api/pr-check", json={"repo": "acme/shop", "head_sha": SHA}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["verdict"] == "pass"
    for method, path in (("GET", "/api/portfolios"), ("GET", "/api/settings/providers"), ("GET", "/api/users")):
        assert ci.request(method, path, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert ci.post("/api/pr-check", json={"repo": "acme/shop", "head_sha": SHA}).status_code == 401
    assert ci.post("/api/pr-check", json={"repo": "acme/shop", "head_sha": SHA}, headers={"Authorization": "Bearer fmea_wrong"}).status_code == 401


def test_tokens_are_shown_once_stored_hashed_listed_masked_and_revocable(ph, api):
    token = make_token(api)
    assert token.startswith("fmea_") and len(token) > 30
    conn = sqlite3.connect(db._DB_PATH)
    stored = conn.execute("SELECT token_hash FROM api_tokens").fetchone()[0]
    conn.close()
    assert token not in stored and token[-6:] not in stored
    listing = api.get("/api/tokens")
    assert token not in listing.text and listing.json()[0]["hint"].endswith(token[-4:])
    token_id = listing.json()[0]["id"]
    assert api.delete(f"/api/tokens/{token_id}").status_code == 200
    from api.main import app
    assert TestClient(app).post("/api/pr-check", json={"repo": "acme/shop", "head_sha": SHA},
                                headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_only_admins_manage_tokens_and_the_audit_trail_names_the_token(ph, api):
    from api.main import app
    api.post("/api/users", json={"username": "dana", "password": "correct-horse-battery", "role": "developer"})
    dev = TestClient(app, headers=CSRF)
    dev.post("/api/auth/login", json={"username": "dana", "password": "correct-horse-battery"})
    assert dev.post("/api/tokens", json={"name": "x"}).status_code == 403 and dev.get("/api/tokens").status_code == 403
    token = make_token(api, "ci-main")
    ph.baseline([failure("A")])
    ph.next_failures = [failure("A")]
    TestClient(app).post("/api/pr-check", json={"repo": "acme/shop", "head_sha": SHA, "pr_number": 7},
                         headers={"Authorization": f"Bearer {token}"})
    conn = sqlite3.connect(db._DB_PATH)
    rows = conn.execute("SELECT username, action, detail FROM audit_events WHERE action IN ('token_created','pr_check')").fetchall()
    conn.close()
    assert ("root", "token_created", "ci-main") in rows
    assert any(u == "token:ci-main" and a == "pr_check" and "acme/shop#7" in d for u, a, d in rows)
    assert token not in str(rows)


def test_project_configuration_is_validated_and_limited_to_security_roles(ph, api):
    from api.main import app
    pid = ph.project["id"]
    assert api.get(f"/api/projects/{pid}/pr-check").json() == {"enabled": True, "fail_severity": 9, "budget_usd": 1.0}
    assert api.put(f"/api/projects/{pid}/pr-check", json={"enabled": True, "fail_severity": 8, "budget_usd": 2.5}).status_code == 200
    assert api.get(f"/api/projects/{pid}/pr-check").json()["fail_severity"] == 8
    for bad in ({"fail_severity": 0}, {"fail_severity": 11}, {"budget_usd": 0}, {"budget_usd": 500}):
        assert api.put(f"/api/projects/{pid}/pr-check", json=bad).status_code == 422
    assert api.put("/api/projects/999/pr-check", json={"enabled": True}).status_code == 404
    api.post("/api/users", json={"username": "dana", "password": "correct-horse-battery", "role": "developer"})
    dev = TestClient(app, headers=CSRF)
    dev.post("/api/auth/login", json={"username": "dana", "password": "correct-horse-battery"})
    assert dev.put(f"/api/projects/{pid}/pr-check", json={"enabled": False}).status_code == 403
    assert dev.get(f"/api/projects/{pid}/pr-check").status_code == 200


def test_an_unknown_repository_is_a_404_with_a_plain_message(ph, api):
    token = make_token(api)
    from api.main import app
    r = TestClient(app).post("/api/pr-check", json={"repo": "nobody/nothing", "head_sha": SHA}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404 and "No project is linked" in r.json()["detail"]


def test_the_request_is_validated(ph, api):
    token = make_token(api)
    from api.main import app
    for body in ({"repo": "not-a-repo", "head_sha": SHA}, {"repo": "acme/shop", "head_sha": "bad sha!"},
                 {"repo": "acme/shop", "head_sha": SHA, "budget_usd": -1}):
        r = TestClient(app).post("/api/pr-check", json=body, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422, body


# ── the CI template ───────────────────────────────────────────────────────────

def test_the_github_actions_template_calls_the_check_and_fails_on_a_failed_verdict():
    text = (ROOT / "docs" / "ci" / "fmea-pr-check.yml").read_text(encoding="utf-8")
    assert "pull_request" in text and "/api/pr-check" in text and "Authorization: Bearer" in text
    assert "secrets.FMEA_TOKEN" in text and "secrets.FMEA_URL" in text
    assert "exit 1" in text and "comment_markdown" in text and "gh pr comment" in text
    assert "github.event.pull_request.head.sha" in text
    try:
        import yaml
    except ImportError:
        return
    assert "jobs" in yaml.safe_load(text)


# ── review follow-ups ─────────────────────────────────────────────────────────

def test_the_budget_stop_is_not_swallowed_by_agents_that_fall_back_on_errors(monkeypatch):
    import agents.llm_judge as judge
    import agents.scenario_linkage as linkage
    import agents.validator as validator
    from core.models import RiskScore

    def out_of_budget(*a, **k):
        raise budget.BudgetReached("limit")

    risk = RiskScore(failure_mode="A", severity=5, occurrence=5, detection=5, rpn=125, priority="High", justification="",
                     severity_rationale="", occurrence_rationale="", detection_rationale="")
    for module, call in ((validator, lambda: validator.run_validator([failure("A")], [risk])),
                         (judge, lambda: judge.run_llm_judge([failure("A")], [risk], [], [])),
                         (linkage, lambda: linkage.run_scenario_linkage([failure("A")], "code"))):
        monkeypatch.setattr(module, "call_llm", out_of_budget)
        with pytest.raises(budget.BudgetReached):
            call()


def test_a_budget_stop_inside_a_late_agent_still_ends_the_check_with_the_notice(ph, monkeypatch):
    ph.baseline([failure("A")])
    monkeypatch.setattr(llm, "get_model_name", lambda: "gpt-5.1")

    def costly_validator(failures, risks):
        llm._add_usage(calls=1, prompt=4_000_000, completion=10_000)           # crosses the limit in the validator
        raise AssertionError("not reached")

    monkeypatch.setattr(pipeline, "run_validator", costly_validator)
    out = ph.check([failure("New", EVIDENCE)], budget_usd=0.25)
    assert out["budget_reached"] is True and out["verdict"] == "pass" and "budget" in out["comment_markdown"].lower()


def test_a_renamed_existing_finding_without_a_stored_identity_is_not_reported_as_new(ph):
    quote = "src/old.py:3 `os.system('ping ' + request.args['host'])`"
    ws = ph.baseline([failure("Command injection in ping", quote)])
    conn = sqlite3.connect(db._DB_PATH)
    conn.execute("UPDATE scenarios SET identity_key=NULL"); conn.commit(); conn.close()       # an old row without identity
    ph.scores["Unsafe shell call"] = (9, 6, 6)
    out = ph.check([failure("Unsafe shell call", "src/net/tools.py:11 `os.system('ping ' + request.args['host'])`")])
    assert out["new"] == [] and out["verdict"] == "pass"


def test_a_same_file_finding_with_a_similar_name_is_treated_as_the_known_one(ph):
    ph.baseline([failure("SQL injection in order lookup", "src/payments/charge.py:10 `cursor.execute(q + order_id)`")])
    ph.scores["SQL injection in the order lookup query"] = (9, 6, 6)
    out = ph.check([failure("SQL injection in the order lookup query", "src/payments/charge.py:12 `cursor.execute(query + oid)`")])
    assert out["new"] == []


def test_a_project_without_a_baseline_says_so_in_the_comment(ph):
    out = ph.check([failure("Anything", EVIDENCE)])
    assert "baseline" in out["comment_markdown"].lower() and out["verdict"] == "pass"


def test_changed_files_that_were_not_examined_are_called_out(ph, monkeypatch):
    ph.baseline([failure("A")])
    ph.tree = classify_tree([("src/app.py", 900), ("deploy/settings.cfg.lock", 50), ("src/payments/charge.py", 900)])
    monkeypatch.setattr(pr_check, "fetch_pr_changes", lambda o, r, n: {"deploy/settings.cfg.lock": None, "src/app.py": None})
    out = ph.check([failure("A")])
    assert out["verdict"] == "pass" and "not examined" in out["comment_markdown"] and "settings.cfg.lock" in out["comment_markdown"]


def test_comment_text_from_the_model_cannot_mention_link_or_inject_html(ph):
    ph.baseline([failure("Existing")])
    ph.scores["@org/security-team [click](http://evil.example/x) <img src=x onerror=1> **bold**"] = (9, 6, 6)
    nasty = "@org/security-team [click](http://evil.example/x) <img src=x onerror=1> **bold**"
    out = ph.check([failure(nasty, EVIDENCE.replace("db.execute", "db.run"))])
    comment = out["comment_markdown"]
    assert out["verdict"] == "fail"
    assert "](http://evil" not in comment and "<img" not in comment and "@org" not in comment.replace("@\u200borg", "")
    assert "evil.example" in comment                                          # shown as text, not as a link


def test_long_model_text_is_truncated(ph):
    ph.baseline([failure("Existing")])
    name = "X" * 5000
    ph.scores[name] = (9, 6, 6)
    out = ph.check([failure(name, EVIDENCE)])
    assert len(out["comment_markdown"]) < 1500


def test_concurrent_checks_for_one_project_are_limited(ph):
    ph.baseline([failure("A")])
    pr_check._active[ph.project["id"]] = pr_check.MAX_CONCURRENT_PER_PROJECT
    try:
        with pytest.raises(pr_check.PrCheckError) as exc:
            ph.check([failure("A")])
        assert exc.value.status == 429
    finally:
        pr_check._active.clear()


def test_a_token_limited_to_one_repository_cannot_check_another(ph, api):
    from api.main import app
    other = db.create_project(ph.portfolio["id"], "web", "https://github.com/acme/website")
    ph.baseline([failure("A")])
    r = api.post("/api/tokens", json={"name": "shop-only", "repo": "acme/shop"})
    assert r.status_code == 201 and r.json()["repo"] == "acme/shop"
    token = r.json()["token"]
    ci = TestClient(app)
    ph.next_failures = [failure("A")]
    assert ci.post("/api/pr-check", json={"repo": "acme/shop", "head_sha": SHA}, headers={"Authorization": f"Bearer {token}"}).status_code == 200
    denied = ci.post("/api/pr-check", json={"repo": "acme/website", "head_sha": SHA}, headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 403 and "limited to acme/shop" in denied.json()["detail"]
    assert api.get("/api/tokens").json()[0]["repo"] == "acme/shop"


def test_the_template_cancels_superseded_runs_and_does_not_comment_on_an_error():
    text = (ROOT / "docs" / "ci" / "fmea-pr-check.yml").read_text(encoding="utf-8")
    assert "cancel-in-progress: true" in text and "timeout-minutes" in text
    assert "%{http_code}" in text and '!= "200"' in text and "steps.check.outputs.verdict != ''" in text


# ── only what the pull request changed is the pull request's ──────────────────

def test_changed_ranges_come_from_the_patch_hunks():
    from core.github_fetcher import changed_ranges
    patch = ("@@ -1,3 +1,4 @@\n import os\n+import sys\n import json\n def f():\n"
             "@@ -20,2 +21,5 @@ def g():\n     a = 1\n+    b = 2\n+    c = 3\n-    d = 4\n+    d = 5\n     return a\n")
    assert changed_ranges(patch) == [(2, 2), (22, 24)]


def test_a_docstring_only_pull_request_passes_even_when_the_model_finds_unrelated_new_things(ph):
    ph.baseline([failure("Existing finding")])
    ph.changes = {"src/app.py": [(10, 12)]}                                   # the pull request touched three lines
    ph.scores["Rate limiting missing"] = (9, 6, 6)
    ph.scores["Another unrelated one"] = (8, 5, 5)
    out = ph.check([failure("Existing finding"),
                    failure("Rate limiting missing", "src/app.py:90 `def login(user, password):`"),
                    failure("Another unrelated one", "src/payments/charge.py:7 `q = 'SELECT ' + request.args['x']`")])
    assert out["verdict"] == "pass" and out["new"] == [] and out["outside_changes"] == 2
    assert out["comment_markdown"] == "" and "outside the changed lines" in out["summary"]


def test_a_finding_on_a_changed_line_or_just_around_it_is_reported(ph):
    ph.baseline([failure("Existing finding")])
    ph.changes = {"src/app.py": [(40, 44)]}
    ph.scores["Near the change"] = (9, 6, 6)
    out = ph.check([failure("Existing finding"), failure("Near the change", "src/app.py:47 `os.system('zip ' + name)`")])
    assert out["verdict"] == "fail" and [n["failure_mode"] for n in out["new"]] == ["Near the change"]
    far = ph.check([failure("Existing finding"), failure("Near the change", "src/app.py:48 `os.system('zip ' + name)`")])
    assert far["new"] == [] and far["outside_changes"] == 1                    # more than three lines away


def test_a_whole_file_change_and_missing_diff_information_report_everything(ph):
    ph.baseline([failure("Existing finding")])
    ph.scores["Anywhere in the file"] = (9, 6, 6)
    ph.changes = {"src/app.py": None}
    out = ph.check([failure("Existing finding"), failure("Anywhere in the file", "src/app.py:900 `eval(request.args['x'])`")])
    assert out["verdict"] == "fail"
    ph.changes = {}                                                           # no pull request number or no diff available
    out = ph.check([failure("Existing finding"), failure("Anywhere in the file", "src/other.py:5 `eval(request.args['x'])`")])
    assert out["verdict"] == "fail"


def test_a_file_the_pull_request_did_not_touch_is_not_the_pull_requests(ph):
    ph.baseline([failure("Existing finding")])
    ph.changes = {"src/app.py": [(1, 5)]}
    ph.scores["In another file"] = (9, 6, 6)
    out = ph.check([failure("Existing finding"), failure("In another file", "src/payments/charge.py:3 `eval(request.args['x'])`")])
    assert out["new"] == [] and out["verdict"] == "pass"
