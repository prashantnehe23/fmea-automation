"""
tests/test_index_scorer.py — B-036 spike: the code-index scorer and truth files

Pure Python: no parser needed.
"""

from pathlib import Path

import pytest

from benchmarks.index_spike import make_truth
from benchmarks.index_spike.score_index import load_truth, score

ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "index_repos"
REPOS = sorted(p for p in ROOT.iterdir() if (p / "index_truth.json").exists())


def perfect(truth):
    return {
        "symbols": [{"file": e[k]["file"], "name": e[k]["symbol"], "line": 1} for e in truth["calls"] for k in ("callee", "caller")],
        "calls": [{"caller_file": e["caller"]["file"], "caller": e["caller"]["symbol"], "callee": e["callee"]["symbol"],
                   "callee_file": e["callee"]["file"]} for e in truth["calls"]],
        "entry_points": [{"file": e["file"], "kind": e["kind"], "symbol": e["symbol"]} for e in truth["entry_points"]],
        "sinks": [{"file": s["file"], "kind": s["kind"], "line": s["line"]} for s in truth["sinks"]],
    }


@pytest.mark.parametrize("repo", REPOS, ids=lambda p: p.name)
def test_truth_files_are_complete_and_current(repo):
    truth = load_truth(repo)
    assert len(truth["entry_points"]) == 3 and len(truth["sinks"]) == 5 and len(truth["calls"]) == 7
    assert {"http", "main"} == {e["kind"] for e in truth["entry_points"]}
    assert {"sql", "file", "command"} == {s["kind"] for s in truth["sinks"]}
    for item in truth["entry_points"] + truth["sinks"]:
        assert (repo / item["file"]).exists()
        assert 1 <= item["line"] <= len((repo / item["file"]).read_text(encoding="utf-8").splitlines())
    assert make_truth.build()[repo.name] == truth, "index_truth.json is stale: rerun benchmarks.index_spike.make_truth"


def test_four_languages_are_covered():
    assert {load_truth(r)["language"] for r in REPOS} == {"python", "java", "csharp", "typescript"}


@pytest.mark.parametrize("repo", REPOS, ids=lambda p: p.name)
def test_a_perfect_index_scores_one(repo):
    truth = load_truth(repo)
    s = score(truth, perfect(truth))
    assert all(s[k] == 1.0 for k in ("call_recall", "call_precision", "symbol_recall", "entry_recall",
                                     "entry_precision", "sink_recall", "sink_precision"))


def test_an_empty_index_scores_zero_and_unprovided_layers_are_none():
    truth = load_truth(REPOS[0])
    s = score(truth, {"symbols": [], "calls": [], "entry_points": [], "sinks": []})
    assert s["call_recall"] == 0.0 and s["entry_recall"] == 0.0 and s["sink_recall"] == 0.0
    assert s["call_precision"] is None and s["entry_precision"] is None
    s = score(truth, {"symbols": [], "calls": [], "entry_points": None, "sinks": None})
    assert s["entry_recall"] is None and s["sink_recall"] is None and s["call_recall"] == 0.0


def test_a_call_is_found_by_name_and_a_wrong_callee_file_does_not_count():
    truth = load_truth(ROOT / "ts-orders")
    pred = perfect(truth)
    assert score(truth, pred)["call_recall"] == 1.0
    pred["calls"][0]["callee_file"] = "src/other.ts"
    assert score(truth, pred)["calls_found"] == 6
    pred["calls"][0].pop("callee_file")                                  # an unresolving tool is judged by name only
    assert score(truth, pred)["calls_found"] == 7


def test_extra_edges_into_labelled_callees_cost_precision():
    truth = load_truth(ROOT / "py-orders")
    pred = perfect(truth)
    pred["calls"].append({"caller_file": "jobs.py", "caller": "nightly_cleanup", "callee": "find"})
    assert score(truth, pred)["call_precision"] == pytest.approx(7 / 8, abs=1e-3)


def test_sink_lines_use_a_tolerance_of_one_and_the_right_kind():
    truth = load_truth(ROOT / "py-orders")
    s0 = truth["sinks"][0]
    near = {"sinks": [{"file": s0["file"], "kind": s0["kind"], "line": s0["line"] + 1}], "calls": [], "symbols": [], "entry_points": []}
    far = {"sinks": [{"file": s0["file"], "kind": s0["kind"], "line": s0["line"] + 20}], "calls": [], "symbols": [], "entry_points": []}
    wrong_kind = {"sinks": [{"file": s0["file"], "kind": "file", "line": s0["line"]}], "calls": [], "symbols": [], "entry_points": []}
    assert score(truth, near)["sink_recall"] == 0.2 and score(truth, far)["sink_recall"] == 0.0
    assert score(truth, wrong_kind)["sink_recall"] == 0.0


def test_http_entry_points_must_name_the_handler_but_main_entries_need_only_the_file():
    truth = load_truth(ROOT / "java-orders")
    pred = perfect(truth)
    pred["entry_points"][0]["symbol"] = "wrongName"
    pred["entry_points"][2]["symbol"] = "anything"
    s = score(truth, pred)
    assert s["entry_recall"] == pytest.approx(2 / 3, abs=1e-3)
