"""
tests/test_index_inhouse.py — B-036 spike: the in-house tree-sitter index prototype

Needs the tree-sitter wheels, which are not project dependencies yet (they arrive with B-036 phase 1);
skipped when they are missing.
"""

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_java")
pytest.importorskip("tree_sitter_c_sharp")
pytest.importorskip("tree_sitter_typescript")
pytest.importorskip("tree_sitter_python")

from benchmarks.index_spike.idiom_probe import probe
from benchmarks.index_spike.inhouse import index_repo
from benchmarks.index_spike.score_index import load_truth, score

ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "index_repos"
REPOS = sorted(p for p in ROOT.iterdir() if (p / "index_truth.json").exists())


@pytest.mark.parametrize("repo", REPOS, ids=lambda p: p.name)
def test_every_labelled_call_entry_point_and_sink_is_found(repo):
    s = score(load_truth(repo), index_repo(repo))
    assert s["call_recall"] == 1.0 and s["symbol_recall"] == 1.0
    assert s["entry_recall"] == 1.0 and s["entry_precision"] == 1.0
    assert s["sink_recall"] == 1.0 and s["sink_precision"] == 1.0


def test_name_based_resolution_conflates_same_named_callees():
    """Known limit recorded in ADR-025: `@router.get(...)`, `app.get(...)` and `db.prepare(...).get(x)` look like calls to a
    method named get. Receiver-aware resolution (B-036 phase 1) must lift these above their current values."""
    py = score(load_truth(ROOT / "py-orders"), index_repo(ROOT / "py-orders"))["call_precision"]
    ts = score(load_truth(ROOT / "ts-orders"), index_repo(ROOT / "ts-orders"))["call_precision"]
    assert py == pytest.approx(0.875, abs=0.01) and ts == pytest.approx(0.778, abs=0.01)


def test_idiom_probe_documents_the_detectors_that_do_not_exist_yet():
    result = probe()
    assert [f for f, ok in result.items() if not ok] == ["django_urls.py", "aspnet_minimal.cs", "Jaxrs.java"]
