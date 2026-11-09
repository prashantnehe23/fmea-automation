"""
tests/test_benchmark_runner.py — B-026 phase 3: benchmark runner, isolation and report (ADR-023)

  AC-R1  a benchmark scan sees exactly the files a real scan would (shared scope rule)
  AC-R2  a benchmark run never touches the real database, memory files or settings
  AC-R3  every run starts in a fresh environment; failures are recorded, not raised
  AC-R4  the budget stops the run and says so; unsigned labels are refused unless allowed
  AC-R5  the report scores stored findings offline
Fake pipeline only: no network, no LLM.
"""

import hashlib
from pathlib import Path

import pytest

import memory.db as db
from benchmarks import report, run
from core import providers, settings
from core.github_fetcher import file_block, select_paths
from core.models import FailureMode, RiskScore

ROOT = Path(__file__).resolve().parents[1]
REPOS = run.REPOS_DIR
KEYS = {"mistral": "test-key-not-real"}


# ── AC-R1 ─────────────────────────────────────────────────────────────────────

def test_select_paths_applies_the_scan_scope_rule():
    paths = ["README.md", "app.py", "src/util.js", "tests/test_app.py", "node_modules/x/index.js",
             ".github/workflows/ci.yml", "Dockerfile", "main.tf", "config.env", "poetry.lock",
             "templates/page.html", "docs/guide.md", "data.json"]
    files, readme = select_paths(paths)
    assert readme == "README.md"
    assert files == sorted(["README.md", "app.py", "src/util.js", "config.env", "docs/guide.md", "data.json"])
    assert "tests/test_app.py" in select_paths(paths, skip_tests=False)[0]


def test_file_block_format_is_the_one_the_fetcher_uses():
    block = file_block("app.py", "x = 1")
    assert block.startswith("# ── app.py ─") and block.endswith("\nx = 1")


def test_scan_input_shows_a_scan_what_a_real_scan_would_see():
    code, context = run.scan_input(REPOS / "infra-deploy")
    assert "# ── config.env" in code and "# ── main.py" in code
    for hidden in ("storage.tf", "Dockerfile", "release.yml", "truth.json"):     # B-033 gaps, and never the labels
        assert hidden not in code
    assert "Deploy repo" in context
    web, _ = run.scan_input(REPOS / "web-templates")
    assert "# ── templates/comments.html" not in web and "# ── app.py" in web


def test_hostile_readme_comment_is_sanitised_but_hostile_code_comment_is_kept():
    code, context = run.scan_input(REPOS / "adversarial-api")
    assert "ignore all previous instructions" not in context.lower()
    assert "ignore previous instructions" in code.lower()          # the code is what the scan is meant to resist


# ── fakes ─────────────────────────────────────────────────────────────────────

def make_result(n=1):
    failures = [FailureMode(failure_mode=f"SQL injection {i}", attack_chain=["a", "b"], business_impact="loss",
                            blast_radius="all", trigger="/orders/search", evidence="app.py:32") for i in range(n)]
    risks = [RiskScore(failure_mode=f.failure_mode, severity=9, occurrence=5, detection=5, rpn=225, priority="High",
                       justification="j", severity_rationale="r", occurrence_rationale="r",
                       detection_rationale="r") for f in failures]
    return {"failures": failures, "risks": risks, "validations": []}


def span(workspace_id, cost):
    db.save_telemetry_span(run_id="r", scan_id=None, workspace_id=workspace_id, agent="saboteur", duration_ms=1.0,
                           prompt_tokens=1, completion_tokens=1, error=None, cost_usd=cost)


def fake_pipeline(cost=0.5, n=1, seen=None, fail=False):
    def fake(code, force_rerun, workspace):
        if seen is not None:
            conn = db.get_db()
            rows = conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
            conn.close()
            seen.append({"rows": rows, "db": str(db._DB_PATH), "key": providers.get_api_key("mistral"),
                         "model": settings.get_setting("active_model"), "code": code,
                         "project": workspace.project})
        if fail:
            raise RuntimeError("model unavailable")
        span(db.upsert_workspace(workspace), cost)
        return make_result(n)
    return fake


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def real_state():
    files = [ROOT / "memory/fmea.db", ROOT / "core/settings.json", ROOT / "memory/learning_memory.json",
             ROOT / "memory/analysis_cache.json", ROOT / "memory/core/eval_history.json",
             ROOT / "memory/core/learning_memory.json"]
    workspaces = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "memory/workspaces").rglob("*"))
    return [digest(f) for f in files], workspaces


# ── AC-R2 / AC-R3 ─────────────────────────────────────────────────────────────

def test_a_benchmark_run_leaves_the_real_stores_untouched():
    from memory import eval_store, workspace_store

    def touches_every_store(code, force_rerun, workspace):
        wid = db.upsert_workspace(workspace)
        workspace_store.cache_result(code, {"fingerprint": "x"}, workspace)
        eval_store._core_eval_path().write_text("[]")
        workspace_store._core_learning_path().write_text("{}")
        settings.set_setting("scratch", 1)
        span(wid, 0.1)
        return make_result()

    before = real_state()
    out = run.run_once(REPOS / "shop-api", "mistral-large-4", "off", 1, KEYS, run_fmea=touches_every_store)
    assert out["error"] is None and out["cost_usd"] == 0.1
    assert real_state() == before


def test_the_run_uses_the_requested_model_a_copied_key_and_a_temporary_database():
    seen, db_before = [], db._DB_PATH
    run.run_once(REPOS / "shop-api", "mistral-medium-latest", "off", 1, KEYS, run_fmea=fake_pipeline(seen=seen))
    [s] = seen
    assert s["model"] == "mistral-medium-latest" and s["key"] == KEYS["mistral"]
    assert Path(s["db"]) != db_before and "fmea-bench-" in s["db"]
    assert "# ── app.py" in s["code"]
    assert db._DB_PATH == db_before                                      # redirection is undone afterwards


def test_every_run_starts_in_a_fresh_environment():
    seen = []
    pipeline = fake_pipeline(cost=0.5, seen=seen)
    a = run.run_once(REPOS / "shop-api", "mistral-large-4", "off", 1, KEYS, run_fmea=pipeline)
    b = run.run_once(REPOS / "shop-api", "mistral-large-4", "off", 2, KEYS, run_fmea=pipeline)
    assert [s["rows"] for s in seen] == [0, 0]               # run 2 does not see run 1's telemetry or scenarios
    assert a["cost_usd"] == b["cost_usd"] == 0.5
    assert [s["project"] for s in seen] == ["shop-api-1", "shop-api-2"]


def test_findings_and_a_failed_scan_are_recorded_not_raised():
    ok = run.run_once(REPOS / "shop-api", "mistral-large-4", "off", 1, KEYS, run_fmea=fake_pipeline(n=2))
    assert [f["failure_mode"] for f in ok["findings"]] == ["SQL injection 0", "SQL injection 1"]
    assert ok["findings"][0]["priority"] == "High" and ok["findings"][0]["severity"] == 9
    bad = run.run_once(REPOS / "shop-api", "mistral-large-4", "off", 1, KEYS, run_fmea=fake_pipeline(fail=True))
    assert bad["findings"] == [] and "model unavailable" in bad["error"]


# ── AC-R4 ─────────────────────────────────────────────────────────────────────

def test_unsigned_labels_are_refused_unless_allowed():
    with pytest.raises(ValueError, match="not signed off"):
        run.run_benchmark("m", "off", 1, [REPOS / "shop-api"], "t", 5.0, False, KEYS, fake_pipeline())
    out = run.run_benchmark("m", "off", 1, [REPOS / "shop-api"], "t", 5.0, True, KEYS, fake_pipeline())
    assert out["meta"]["signed_off"] == {"shop-api": None}


def test_the_budget_stops_the_run_and_says_so():
    out = run.run_benchmark("m", "off", 3, [REPOS / "shop-api", REPOS / "chain-api"], "t", 1.0, True, KEYS,
                            fake_pipeline(cost=0.6))
    assert len(out["repos"]["shop-api"]["runs"]) == 2        # 0.6, then 1.2 >= 1.0: no third scan
    assert "shop-api run 3" in out["meta"]["stopped"] and out["meta"]["total_cost_usd"] == 1.2
    assert "chain-api" not in out["repos"] or out["repos"]["chain-api"]["runs"] == []


def test_the_result_records_the_commit_and_run_settings():
    out = run.run_benchmark("mistral-large-4", "high", 1, [REPOS / "shop-api"], "baseline", 5.0, True, KEYS,
                            fake_pipeline())
    meta = out["meta"]
    assert (meta["model"], meta["reasoning"], meta["label"], meta["runs"]) == ("mistral-large-4", "high", "baseline", 1)
    assert len(meta["git"]["commit"]) == 40


# ── AC-R5 ─────────────────────────────────────────────────────────────────────

def stored(runs_by_repo, signed=None):
    return {"meta": {"label": "t", "model": "m", "reasoning": "off", "runs": 2, "created": "2026-11-09",
                     "signed_off": {n: signed for n in runs_by_repo}, "stopped": None},
            "repos": {n: {"runs": r} for n, r in runs_by_repo.items()}}


def run_record(findings, cost=0.25, error=None):
    return {"findings": findings, "error": error, "cost_usd": cost, "seconds": 10.0, "llm_calls": 9}


SQLI = {"failure_mode": "SQL injection", "trigger": "q parameter of /orders/search",
        "evidence": "app.py:32 f-string reaches db().execute", "priority": "High"}
REFUND = {"failure_mode": "No role check on refund", "trigger": "/admin/refund",
          "evidence": "app.py:38 only checks login; any customer can update refunded orders", "priority": "Medium"}


def test_report_scores_stored_findings_offline():
    s = report.summarise(stored({"shop-api": [run_record([SQLI, REFUND]), run_record([SQLI])]}))
    repo, overall = s["repos"]["shop-api"], s["overall"]
    assert repo["recall"] == 0.375                           # 3 matches over 2 runs x 4 labels
    assert repo["catastrophic_recall"] == 0.75               # 3 of 4 catastrophic labels, pooled
    assert repo["placement"] == 0.667                        # SQLi High, refund Medium, SQLi High
    assert repo["path_accuracy"] == 1.0 and repo["precision"] == 1.0
    assert repo["stability"] == 0.5                          # shop-001 in both runs, shop-002 in one
    assert repo["missed_catastrophic"] == ["shop-002"] and overall["cost_usd"] == 0.5


def test_report_excludes_failed_scans_and_counts_them():
    s = report.summarise(stored({"shop-api": [run_record([SQLI]), run_record([], error="boom")]}))
    assert s["repos"]["shop-api"]["runs_ok"] == 1 and s["overall"]["runs_failed"] == 1
    assert s["repos"]["shop-api"]["stability"] is None       # one good run: stability not defined


def test_table_warns_about_unsigned_labels_and_budget_stops():
    data = stored({"shop-api": [run_record([SQLI])]})
    data["meta"]["stopped"] = "budget $1.00 reached"
    text = report.format_table([report.summarise(data)])
    assert "labels NOT signed off" in text and "STOPPED" in text and "OVERALL" in text
    assert "missed catastrophic: shop-api: shop-002" in text
