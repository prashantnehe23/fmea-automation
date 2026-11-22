"""
B-028 phase 0 — no cap on what is reported; large repositories in prioritised batches; cost estimate.

  AC  7 locked findings plus a new vulnerability reports all 8; max_failure_modes no longer limits reporting
  AC  a 1 MB repository is fully processed, or the files not processed are listed
  AC  a single-batch scan makes the same model calls as before (Quick depth keeps today's cost)
  AC  the estimate is shown before a scan that costs more than a single pass
  (Recall and precision on the B-026 benchmark need real model runs: not testable here, see the backlog.)
"""

import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import agents.saboteur as saboteur
import memory.db as db
import workflows.fmea_pipeline as pipeline
from core import estimate as estimator
from core.line_numbers import number_lines
from core.models import ControlAssessment, ScenarioExplanation, ScenarioLinkageReport, SystemContext
from core.scan_scope import MAX_BYTES, ScopeEntry, build_scan_input, classify_tree, plan_batches
from test_finding_lifecycle import WS, Harness, failure


def entries(n, size, prefix="src/mod"):
    return [ScopeEntry(f"{prefix}{i:02d}.py", True, "code file", "code", size) for i in range(n)]


# ── batches ───────────────────────────────────────────────────────────────────

def test_batches_respect_the_budget_and_keep_every_file_in_exactly_one_batch():
    items = entries(40, 25_000)                                              # 1 MB
    batches, over = plan_batches(items, budget=MAX_BYTES, max_batches=5)
    assert over == [] and 3 <= len(batches) <= 5
    assert all(sum(e.size for e in b) <= MAX_BYTES for b in batches)
    flat = [e.path for b in batches for e in b]
    assert sorted(flat) == sorted(e.path for e in items) and len(flat) == len(set(flat))


def test_high_priority_files_land_in_the_first_batches():
    items = entries(30, 25_000) + [ScopeEntry("deploy/Dockerfile", True, "infra file", "infra", 25_000),
                                   ScopeEntry("src/auth/login.py", True, "code file", "code", 25_000)]
    batches, _ = plan_batches(items, budget=100_000, max_batches=10)
    assert "deploy/Dockerfile" in [e.path for e in batches[0]] and "src/auth/login.py" in [e.path for e in batches[0]]


def test_a_batch_limit_lists_what_was_left_out_in_priority_order():
    items = entries(40, 25_000)
    batches, over = plan_batches(items, budget=MAX_BYTES, max_batches=2)
    assert len(batches) == 2 and len(over) == 40 - sum(len(b) for b in batches) > 0


def test_a_file_bigger_than_the_budget_gets_a_batch_of_its_own():
    big = ScopeEntry("src/huge.py", True, "code file", "code", MAX_BYTES * 2)
    batches, over = plan_batches([big] + entries(3, 1_000), budget=MAX_BYTES, max_batches=5)
    assert over == [] and [e.path for b in batches for e in b if e.size > MAX_BYTES] == ["src/huge.py"]


def contents_for(n, size):
    return {f"src/mod{i:02d}.py": "x = 1\n" + "# filler\n" * (size // 9) for i in range(n)}


def test_a_one_megabyte_repository_is_fully_processed_with_enough_batches():
    scan = build_scan_input(contents_for(40, 25_000), max_batches=5)
    assert len(scan.examined) == 40 and not [m for m in scan.manifest if m["status"] == "unexamined"]
    assert len(scan.batch_codes) >= 3
    assert all(any(f"# ── {p} " in code for code in scan.batch_codes) for p in scan.examined)
    headers = scan.code.split("# ── ")[1:]
    assert len(headers) == sum(code.count("# ── ") for code in scan.batch_codes) == 40
    assert headers == sorted(headers)                                         # path order: a stable cache key


def test_a_one_megabyte_repository_lists_what_it_did_not_process_when_limited():
    scan = build_scan_input(contents_for(40, 25_000), max_batches=2)
    unexamined = [m for m in scan.manifest if m["status"] == "unexamined"]
    assert unexamined and len(scan.examined) + len(unexamined) == 40
    assert all(m["reason"] for m in unexamined)


def test_default_scope_building_is_unchanged_single_pass():
    scan = build_scan_input(contents_for(40, 25_000))                        # callers that do not ask for batches
    assert len(scan.batch_codes) == 1 and [m for m in scan.manifest if m["status"] == "unexamined"]


# ── estimate ──────────────────────────────────────────────────────────────────

def test_estimate_grows_with_batches_and_flags_more_than_a_single_pass(monkeypatch):
    monkeypatch.setattr(estimator, "get_model_name", lambda: "gpt-5.1")
    one = estimator.estimate_scan([200_000])
    four = estimator.estimate_scan([300_000] * 4)
    assert one["batches"] == 1 and one["exceeds_single_pass"] is False
    assert four["batches"] == 4 and four["exceeds_single_pass"] is True
    assert four["calls"] > one["calls"] and four["usd"] > one["usd"] > 0
    assert four["single_pass_usd"] <= four["usd"] and set(four) >= {"calls", "prompt_tokens", "usd", "model"}


def test_estimate_with_no_files_is_zero(monkeypatch):
    monkeypatch.setattr(estimator, "get_model_name", lambda: "gpt-5.1")
    assert estimator.estimate_scan([])["calls"] == 0


# ── the saboteur prompt ───────────────────────────────────────────────────────

def capture_prompt(monkeypatch, **kw):
    captured = {}
    monkeypatch.setattr(saboteur, "call_llm", lambda prompt, max_tokens=4096: captured.setdefault("p", prompt) and "[]")
    saboteur.run_saboteur("code", SystemContext(tiering={}, attack_surfaces=[], failure_domains=[]), **kw)
    return captured["p"]


def test_without_a_cap_the_prompt_asks_for_every_weakness(monkeypatch):
    prompt = capture_prompt(monkeypatch, max_scenarios=None)
    assert "at most" not in prompt.lower()


def test_a_part_note_tells_the_model_it_sees_one_part_of_a_repository(monkeypatch):
    prompt = capture_prompt(monkeypatch, locked_names=["Known"], part=(2, 3))
    assert "part 2 of 3" in prompt and "another part" in prompt


def test_a_single_pass_prompt_has_no_part_note(monkeypatch):
    assert "part " not in capture_prompt(monkeypatch, locked_names=["Known"]).lower().replace("particular", "")


# ── the pipeline ──────────────────────────────────────────────────────────────

class BatchHarness(Harness):
    """Scripted agents that remember which code each call saw."""

    def __init__(self, monkeypatch, tmp_path):
        super().__init__(monkeypatch, tmp_path)
        self.per_batch: list[list] = []
        self.calls = {"surveyor": [], "saboteur": [], "controls": [], "linkage": []}
        monkeypatch.setattr(pipeline, "run_surveyor", self._surveyor)
        monkeypatch.setattr(pipeline, "run_scenario_linkage", self._linkage)
        monkeypatch.setattr(pipeline, "run_controls_assessor", self._controls)

    def _surveyor(self, code, business_context=""):
        self.calls["surveyor"].append(code)
        n = len(self.calls["surveyor"])
        return SystemContext(tiering={f"svc{n}": "Tier 1"}, attack_surfaces=[f"surface {n}", "shared"], failure_domains=[])

    def _saboteur(self, code, context, **kw):
        self.saboteur_calls.append(kw)
        self.calls["saboteur"].append(code)
        i = len(self.calls["saboteur"]) - 1
        return list(self.per_batch[i]) if self.per_batch else list(self.next_failures)

    def _controls(self, failures, code):
        self.calls["controls"].append((code, [f.failure_mode for f in failures]))
        return [ControlAssessment(failure_mode=f.failure_mode, controls={}, control_maturity="Low", gaps=[]) for f in failures]

    def _linkage(self, failures, code):
        self.calls["linkage"].append(code)
        return ScenarioLinkageReport(explanations=[
            ScenarioExplanation(failure_mode=f.failure_mode, scenario_summary="s", code_connection="c",
                                links_to_other_scenarios="l") for f in failures], cross_cutting_themes="theme")

    def scan_batches(self, per_batch, codes, **kw):
        self.per_batch = per_batch
        for k in self.calls:
            self.calls[k].clear()
        self.saboteur_calls.clear()
        return pipeline.run_fmea("\n\n".join(codes), workspace=WS, force_rerun=True, batches=codes, **kw)


@pytest.fixture
def bh(monkeypatch, tmp_path):
    return BatchHarness(monkeypatch, tmp_path)


def test_no_cap_reports_every_finding_and_never_truncates(bh):
    many = [failure(f"Finding {i}") for i in range(12)]
    result = bh.scan(many, max_failure_modes=None)
    assert len(result["failures"]) == 12 and bh.saboteur_calls[0]["max_scenarios"] is None


def test_seven_locked_findings_plus_a_new_vulnerability_with_no_cap(bh):
    names = [f"Locked {i}" for i in range(7)]
    bh.scan([failure(n) for n in names], max_failure_modes=None)
    result = bh.scan([failure(n) for n in names] + [failure("Brand new")], code="v2", max_failure_modes=None)
    assert len(result["failures"]) == 8 and result["new_scenarios"] == ["Brand new"]


def test_a_single_pass_scan_makes_the_same_model_calls_as_before(bh):
    bh.scan([failure("A"), failure("B")])
    assert {k: len(v) for k, v in bh.calls.items()} == {"surveyor": 1, "saboteur": 1, "controls": 1, "linkage": 1}
    assert bh.saboteur_calls[0]["max_scenarios"] == 7 and bh.saboteur_calls[0].get("part") is None


def test_batches_are_scanned_separately_and_the_results_merged(bh):
    codes = ["# ── a.py ──\nbatch one", "# ── b.py ──\nbatch two", "# ── c.py ──\nbatch three"]
    result = bh.scan_batches([[failure("F1"), failure("Shared")], [failure("shared"), failure("F2")], [failure("F3")]], codes)
    assert len(bh.calls["saboteur"]) == 3 and len(bh.calls["surveyor"]) == 3
    assert [c["part"] for c in bh.saboteur_calls] == [(1, 3), (2, 3), (3, 3)]
    assert sorted(f.failure_mode for f in result["failures"]) == ["F1", "F2", "F3", "Shared"]     # duplicate merged once
    assert {c[0]: c[1] for c in bh.calls["controls"]}[number_lines(codes[1])] == ["F2"]                         # controls see their own code
    assert len(result["risks"]) == len(result["remediations"]) == len(result["validations"]) == 4
    assert result["batches"] == 3
    assert set(result["context"].tiering) == {"svc1", "svc2", "svc3"} and result["context"].attack_surfaces.count("shared") == 1
    assert [e.failure_mode for e in result["scenario_linkage"].explanations].count("F2") == 1


def test_findings_with_different_names_are_never_merged_even_when_they_quote_the_same_line(bh):
    quote = "src/a.py:3 `cursor.execute('SELECT * FROM t WHERE id=' + request.args['id'])`"
    result = bh.scan_batches([[failure("SQL injection", quote)], [failure("Missing authorisation on the query", quote)]],
                             ["part one", "part two"])
    assert sorted(f.failure_mode for f in result["failures"]) == ["Missing authorisation on the query", "SQL injection"]


def test_a_locked_finding_living_in_a_later_batch_is_not_flagged_as_fixed(bh):
    first = bh.scan([failure("In batch three"), failure("Elsewhere")])
    ws = first["workspace_id"]
    bh.scan_batches([[failure("Elsewhere")], [], [failure("In batch three")]], ["p1", "p2", "p3"])
    assert bh.states(ws) == {"In batch three": "confirmed", "Elsewhere": "confirmed"}
    bh.scan_batches([[failure("Elsewhere")], [], []], ["p1", "p2", "p3"])                 # no batch reports it any more
    assert bh.states(ws)["In batch three"] == "fix_candidate"


# ── the GitHub route ──────────────────────────────────────────────────────────

def github_client(monkeypatch, file_count, size):
    import api.routers.github as gh
    from api.main import app
    tree = classify_tree([(f"src/mod{i:02d}.py", size) for i in range(file_count)])
    monkeypatch.setattr(gh, "list_repo", lambda url: (NS(owner="o", repo="r", branch="main"), tree, None))
    monkeypatch.setattr(gh, "fetch_contents", lambda ref, paths: ({p: "x = 1\n" + "# filler\n" * (size // 9) for p in paths}, {}))
    captured = {}
    monkeypatch.setattr(gh, "run_fmea", lambda code, **kw: captured.update(kw, code=code) or {"failures": [], "risks": []})
    return TestClient(app, headers={"X-Requested-With": "fmea"}), captured


def test_the_github_scan_passes_batches_and_no_cap_to_the_pipeline(monkeypatch):
    client, captured = github_client(monkeypatch, 40, 25_000)
    with client.stream("POST", "/api/github/scan", json={"repo_url": "https://github.com/o/r"}) as r:
        "".join(r.iter_text())
    assert captured["max_failure_modes"] is None and len(captured["batches"]) >= 3
    assert captured["scope"]["summary"]["unexamined"] == 0


def test_the_batch_limit_in_the_request_is_honoured_and_leftovers_are_reported(monkeypatch):
    client, captured = github_client(monkeypatch, 40, 25_000)
    with client.stream("POST", "/api/github/scan", json={"repo_url": "https://github.com/o/r", "max_batches": 2}) as r:
        "".join(r.iter_text())
    assert len(captured["batches"]) == 2 and captured["scope"]["summary"]["unexamined"] > 0


def test_a_small_repository_is_one_batch(monkeypatch):
    client, captured = github_client(monkeypatch, 5, 10_000)
    with client.stream("POST", "/api/github/scan", json={"repo_url": "https://github.com/o/r"}) as r:
        "".join(r.iter_text())
    assert len(captured["batches"]) == 1


def test_preview_includes_the_estimate_before_any_model_call(monkeypatch):
    import api.routers.github as gh
    client, _ = github_client(monkeypatch, 40, 25_000)
    monkeypatch.setattr(estimator, "get_model_name", lambda: "gpt-5.1")
    r = client.post("/api/github/preview", json={"repo_url": "https://github.com/o/r"})
    est = r.json()["estimate"]
    assert r.status_code == 200 and est["exceeds_single_pass"] is True and est["batches"] >= 3 and est["usd"] > 0
    assert est["files_unexamined"] == 0
    small, _ = github_client(monkeypatch, 3, 5_000)
    assert small.post("/api/github/preview", json={"repo_url": "https://github.com/o/r"}).json()["estimate"]["exceeds_single_pass"] is False


# ── review follow-ups ─────────────────────────────────────────────────────────

def counting(monkeypatch, bh):
    sizes = {"actuary": [], "validator": [], "sre": 0}
    real_score = bh._score

    def score(failures, controls, context, business_context="", locked_rpn=None):
        sizes["actuary"].append(len(failures))
        return real_score(failures, controls, context, business_context, locked_rpn)

    def validate(failures, risks):
        from core.models import ValidationResult
        sizes["validator"].append(len(failures))
        return [ValidationResult(failure_mode=f.failure_mode) for f in failures]

    def sre(f, c, r):
        from core.models import RemediationPlan
        sizes["sre"] += 1
        return RemediationPlan(failure_mode=f.failure_mode, fixes=["real plan"], monitoring=[], resilience_upgrades=[])

    monkeypatch.setattr(pipeline, "score_all_failures", score)
    monkeypatch.setattr(pipeline, "run_validator", validate)
    monkeypatch.setattr(pipeline, "run_sre_agent", sre)
    return sizes


def test_many_findings_are_scored_and_validated_in_chunks_so_none_are_lost(bh, monkeypatch):
    sizes = counting(monkeypatch, bh)
    result = bh.scan([failure(f"Finding {i}") for i in range(25)], max_failure_modes=None)
    assert sizes["actuary"] == [10, 10, 5] and sizes["validator"] == [10, 10, 5]
    assert len(result["risks"]) == len(result["validations"]) == len(result["remediations"]) == 25


def test_up_to_ten_findings_still_use_one_call_per_shared_agent(bh, monkeypatch):
    sizes = counting(monkeypatch, bh)
    bh.scan([failure(f"Finding {i}") for i in range(7)])
    assert sizes["actuary"] == [7] and sizes["validator"] == [7] and sizes["sre"] == 7
    assert {k: len(v) for k, v in bh.calls.items()} == {"surveyor": 1, "saboteur": 1, "controls": 1, "linkage": 1}


def test_remediation_plans_stop_at_the_per_scan_limit_and_say_so(bh, monkeypatch):
    sizes = counting(monkeypatch, bh)
    result = bh.scan([failure(f"Finding {i}") for i in range(pipeline.MAX_REMEDIATION_PLANS + 6)], max_failure_modes=None)
    assert sizes["sre"] == pipeline.MAX_REMEDIATION_PLANS
    assert len(result["remediation_limit"]["skipped"]) == 6 and len(result["remediations"]) == pipeline.MAX_REMEDIATION_PLANS + 6
    placeholder = next(r for r in result["remediations"] if r.failure_mode in result["remediation_limit"]["skipped"])
    assert "limit of" in placeholder.fixes[0]


def test_missing_control_assessments_are_padded_not_a_crash(bh, monkeypatch):
    monkeypatch.setattr(pipeline, "run_controls_assessor", lambda f, c: [])          # the model returned nothing
    result = bh.scan([failure("A"), failure("B")])
    assert [c.control_maturity for c in result["controls"]] == ["Unknown", "Unknown"] and len(result["risks"]) == 2


def test_a_cap_never_cuts_locked_findings_in_later_batches(bh):
    bh.scan([failure("Locked in batch two")])
    result = bh.scan_batches([[failure("New one"), failure("New two"), failure("New three")], [failure("Locked in batch two")]],
                             ["p1", "p2"], max_failure_modes=1)
    reported = [f.failure_mode for f in result["failures"]]
    assert "Locked in batch two" in reported and len([n for n in reported if n.startswith("New")]) == 1


def test_estimate_gives_an_upper_figure_and_says_when_the_price_is_assumed(monkeypatch):
    monkeypatch.setattr(estimator, "get_model_name", lambda: "gpt-5.1")
    est = estimator.estimate_scan([300_000] * 5)
    assert est["usd_max"] >= est["usd"] > est["single_pass_usd"] and est["rates_known"] is True
    monkeypatch.setattr(estimator, "get_model_name", lambda: "some-unknown-model")
    assert estimator.estimate_scan([300_000])["rates_known"] is False


def test_remediation_calls_never_exceed_what_the_upper_estimate_assumes(bh, monkeypatch):
    sizes = counting(monkeypatch, bh)
    bh.scan([failure(f"Finding {i}") for i in range(80)], max_failure_modes=None)
    assert sizes["sre"] <= pipeline.MAX_REMEDIATION_PLANS


def test_a_failed_download_and_an_empty_batch_do_not_break_the_batches():
    full = contents_for(40, 25_000)
    contents = dict(full)
    last = sorted(contents)[-14:]
    for path in last:
        del contents[path]                                                   # the last files could not be downloaded
    scan = build_scan_input(contents, classify_tree([(p, 25_000) for p in full]), max_batches=5)
    failed = [m for m in scan.manifest if m["reason"] == "could not be downloaded"]
    assert len(failed) == 14 and all(code for code in scan.batch_codes)
    assert len(scan.examined) == 26 and not set(last) & set(scan.examined)


def test_secrets_are_redacted_in_every_batch():
    contents = contents_for(40, 25_000)
    last = sorted(contents)[-1]
    contents[last] += '\naws_key = "AKIAABCDEFGHIJKLMNOP"\n'
    scan = build_scan_input(contents, max_batches=5)
    assert "AKIAABCDEFGHIJKLMNOP" not in scan.code and all("AKIAABCDEFGHIJKLMNOP" not in c for c in scan.batch_codes)
    assert any(f["path"] == last for f in scan.secret_findings)


def test_the_request_may_ask_for_ten_batches_and_the_preview_estimate_follows_it(monkeypatch):
    client, _ = github_client(monkeypatch, 40, 25_000)
    monkeypatch.setattr(estimator, "get_model_name", lambda: "gpt-5.1")
    few = client.post("/api/github/preview", json={"repo_url": "https://github.com/o/r", "max_batches": 2}).json()["estimate"]
    many = client.post("/api/github/preview", json={"repo_url": "https://github.com/o/r", "max_batches": 10}).json()["estimate"]
    assert few["batches"] == 2 and few["files_unexamined"] > 0 and many["batches"] >= 3 and many["files_unexamined"] == 0
    assert client.post("/api/github/preview", json={"repo_url": "https://github.com/o/r", "max_batches": 11}).status_code == 422
