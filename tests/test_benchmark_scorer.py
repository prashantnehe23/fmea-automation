"""
tests/test_benchmark_scorer.py — B-026 phase 1: benchmark scorer and truth schema (ADR-023)

  AC-T1  truth files are validated (schema, closed vocabularies, file and line ranges)
  AC-T2  scorer: perfect, empty, partial and extra-findings scans
  AC-T3  matching is deterministic, one-to-one, and the semantic fallback is logged
  AC-T4  catastrophic recall, placement, evidence validity, root-cause agreement, stability
Synthetic scans only: no network, no LLM.
"""

import json
import shutil
from pathlib import Path

import pytest

from benchmarks.score import (
    evidence_valid, load_repo_files, load_truth, match_findings, score_scan, stability,
)

REPO = Path(__file__).resolve().parents[1] / "benchmarks" / "repos" / "shop-api"


@pytest.fixture(scope="module")
def truth():
    return load_truth(REPO)


@pytest.fixture(scope="module")
def files():
    return load_repo_files(REPO)


SQLI = {"failure_mode": "SQL injection in order search", "evidence": "app.py:32 builds SQL with an f-string",
        "priority": "Critical", "root_cause": "engineering"}
REFUND = {"failure_mode": "Any customer can refund orders", "trigger": "missing role check in app.py",
          "evidence": "app.py:38 refund() only checks login; no privilege check", "priority": "Medium",
          "root_cause": "architectural"}
SECRET = {"failure_mode": "Hardcoded JWT secret", "evidence": "config.py:2 JWT_SECRET committed", "priority": "High"}
TRACE = {"failure_mode": "Stack traces returned", "evidence": "app.py:52 traceback in error handler", "priority": "Low"}
NOISE = {"failure_mode": "Missing rate limiting", "evidence": "no limits anywhere", "priority": "Medium"}


# ── Truth files ───────────────────────────────────────────────────────────────

def test_seed_truth_loads_and_has_catastrophic_items(truth):
    assert len(truth["items"]) == 4
    assert sum(i["catastrophic"] for i in truth["items"]) == 2


def test_unsigned_truth_is_refused_when_signoff_required():
    with pytest.raises(ValueError, match="not signed off"):
        load_truth(REPO, require_signed_off=True)


def _broken_repo(tmp_path, mutate):
    dest = tmp_path / "r"
    shutil.copytree(REPO, dest)
    data = json.loads((dest / "truth.json").read_text())
    mutate(data)
    (dest / "truth.json").write_text(json.dumps(data))
    return dest


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["items"][0].update(threat_class="made_up"), "unknown threat_class"),
    (lambda d: d["items"][0].update(root_cause_domain="nope"), "unknown root_cause_domain"),
    (lambda d: d["items"][0].update(file="missing.py"), "not in the repository"),
    (lambda d: d["items"][0].update(lines=[1, 999]), "outside"),
    (lambda d: d["items"][0].update(keywords=[]), "keywords are empty"),
    (lambda d: d["items"][1].update(id=d["items"][0]["id"]), "duplicate id"),
    (lambda d: d.update(items=[]), "no truth items"),
])
def test_invalid_truth_is_rejected(tmp_path, mutate, message):
    with pytest.raises(ValueError, match=message):
        load_truth(_broken_repo(tmp_path, mutate))


# ── Scoring ───────────────────────────────────────────────────────────────────

def test_perfect_scan(truth, files):
    s = score_scan([SQLI, REFUND, SECRET, TRACE], truth, files)
    assert (s["recall"], s["precision"], s["catastrophic_recall"]) == (1.0, 1.0, 1.0)
    assert s["missed"] == [] and s["false_positives"] == []


def test_empty_scan(truth, files):
    s = score_scan([], truth, files)
    assert s["recall"] == 0.0 and s["catastrophic_recall"] == 0.0
    assert s["precision"] is None and s["evidence_validity"] is None
    assert s["missed_catastrophic"] == ["shop-001", "shop-002"]


def test_partial_scan_with_extra_finding(truth, files):
    s = score_scan([SQLI, SECRET, NOISE], truth, files)
    assert s["found"] == ["shop-001", "shop-003"]
    assert s["recall"] == 0.5
    assert s["precision"] == pytest.approx(0.6667, abs=1e-4)
    assert s["catastrophic_recall"] == 0.5
    assert s["missed_catastrophic"] == ["shop-002"]
    assert s["false_positives"] == ["Missing rate limiting"]


def test_one_finding_cannot_satisfy_two_truth_items(truth, files):
    both = {"failure_mode": "SQL injection and missing role check", "evidence": "app.py f-string; privilege"}
    s = score_scan([both], truth, files)
    assert s["counts"]["matched"] == 1 and s["precision"] == 1.0


def test_a_file_name_alone_does_not_match(truth, files):
    vague = {"failure_mode": "Problems in app.py", "evidence": "app.py is messy"}
    assert score_scan([vague], truth, files)["recall"] == 0.0


def test_two_keywords_match_without_a_file(truth, files):
    f = {"failure_mode": "Hardcoded secret lets attackers forge tokens"}
    assert score_scan([f], truth, files)["found"] == ["shop-003"]


def test_matching_is_deterministic(truth):
    runs = [match_findings([REFUND, SQLI, SECRET, TRACE], truth["items"])[0] for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


# ── Semantic fallback ─────────────────────────────────────────────────────────

def test_judge_only_sees_leftovers_and_is_logged(truth, files):
    odd = {"failure_mode": "Customers can move money they do not own", "evidence": "app.py"}
    asked = []

    def judge(finding, item):
        asked.append(item["id"])
        return item["id"] == "shop-002"

    s = score_scan([SQLI, odd], truth, files, judge=judge)
    assert "shop-001" not in asked                      # already matched deterministically
    assert "shop-002" in s["found"]
    assert {"truth": "shop-002", "finding": 1, "match": True} in s["judge_log"]


def test_no_judge_means_empty_log(truth, files):
    assert score_scan([SQLI], truth, files)["judge_log"] == []


# ── Placement, evidence, root cause, stability ────────────────────────────────

def test_placement_counts_catastrophic_findings_in_high_or_above(truth, files):
    s = score_scan([SQLI, REFUND], truth, files)         # Critical and Medium
    assert s["placement"] == 0.5


def test_evidence_validity(files):
    assert evidence_valid({"evidence": "see app.py:32"}, files)
    assert evidence_valid({"evidence": "in config.py"}, files)
    assert not evidence_valid({"evidence": "app.py:9999"}, files)
    assert not evidence_valid({"evidence": "ghost.py:3"}, files)
    assert not evidence_valid({}, files)


def test_root_cause_agreement_uses_only_findings_that_state_one(truth, files):
    s = score_scan([SQLI, REFUND, SECRET], truth, files)  # engineering ok, architectural wrong, none
    assert s["root_cause_agreement"] == 0.5
    assert score_scan([SECRET], truth, files)["root_cause_agreement"] is None


def test_stability(truth, files):
    a = score_scan([SQLI, SECRET], truth, files)
    b = score_scan([SQLI, REFUND], truth, files)
    assert stability([a, b]) == pytest.approx(0.3333, abs=1e-4)   # 1 of 3 found in every run
    assert stability([a, a]) == 1.0
    assert stability([score_scan([], truth, files)]) is None
