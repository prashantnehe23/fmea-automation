"""
tests/test_scan_scope.py — B-033 phase 1: scan scope, manifest and budget (ADR-021)

  AC1  every scan carries a scope manifest with an explicit reason for every path not examined
  AC2  the results can say "N examined, M not examined"
  AC3  infrastructure, CI, env files and web templates are in scope
  AC6  a repository over the budget yields a prioritised subset plus an explicit unexamined list, never a silent cut
"""

from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from core.scan_scope import (
    MAX_BYTES, ScopeEntry, build_scan_input, choose_within_budget, classify_path, classify_tree,
    make_manifest, priority, readme_path, summarise_manifest,
)


# ── AC3: what is in scope ─────────────────────────────────────────────────────

@pytest.mark.parametrize("path, category", [
    ("Dockerfile", "infra"), ("api/Dockerfile.prod", "infra"), ("docker-compose.yml", "infra"),
    ("infra/main.tf", "infra"), ("infra/prod.tfvars", "infra"), ("Makefile", "infra"), ("Jenkinsfile", "infra"),
    (".github/workflows/release.yml", "ci"), (".github/actions/setup/action.yml", "ci"),
    (".env", "env"), (".env.production", "env"), ("config.env", "env"),
    ("templates/page.html", "template"), ("ui/App.vue", "template"), ("Views/Home.cshtml", "template"),
    ("pom.xml", "manifest"), ("go.mod", "manifest"), ("requirements-dev.txt", "manifest"), ("App/App.csproj", "manifest"),
    ("src/Service.cs", "code"), ("src/Main.java", "code"), ("web/app.tsx", "code"), ("build.gradle", "manifest"),
    ("README.md", "doc"), ("conf/app.yaml", "config"),
])
def test_in_scope_files_are_classified(path, category):
    e = classify_path(path)
    assert e.included and e.category == category, e


@pytest.mark.parametrize("path, reason", [
    ("node_modules/x/index.js", "noise directory"), (".github/ISSUE_TEMPLATE/bug.md", "noise directory"),
    ("poetry.lock", "lockfile (dependency inventory)"), ("package-lock.json", "lockfile (dependency inventory)"),
    ("app.pyc", "binary or generated"), ("tests/test_app.py", "test file"), ("logo.png", "file type not scanned"),
])
def test_every_exclusion_has_a_stated_reason(path, reason):
    e = classify_path(path)
    assert not e.included and e.reason == reason


def test_tests_can_be_included_on_request():
    assert classify_path("tests/test_app.py", skip_tests=False).included


def test_windows_separators_are_normalised():
    assert classify_path(r".github\workflows\ci.yml").included


def test_root_readme_is_found_only_at_the_root():
    assert readme_path(["docs/README.md", "README.rst", "a.py"]) == "README.rst"
    assert readme_path(["docs/README.md"]) is None


# ── AC1 / AC2: the manifest ───────────────────────────────────────────────────

def test_manifest_lists_every_path_exactly_once_with_a_reason():
    paths = ["app.py", "Dockerfile", "node_modules/a.js", "logo.png", "tests/test_a.py", "big.py"]
    entries = classify_tree([(p, 10) for p in paths])
    manifest = make_manifest(entries, unexamined={"big.py"}, not_selected={"app.py"})
    assert sorted(m["path"] for m in manifest) == sorted(paths)
    assert all(m["reason"] for m in manifest)
    status = {m["path"]: (m["status"], m["reason"]) for m in manifest}
    assert status["Dockerfile"][0] == "examined"
    assert status["app.py"] == ("excluded", "not selected by the user")
    assert status["big.py"] == ("unexamined", "over the size budget")
    assert status["logo.png"] == ("excluded", "file type not scanned")


def test_summary_counts_and_reasons():
    entries = classify_tree([("a.py", 1), ("b.py", 1), ("logo.png", 1), ("poetry.lock", 1)])
    summary = summarise_manifest(make_manifest(entries, unexamined={"b.py"}))
    assert (summary["examined"], summary["unexamined"], summary["excluded"], summary["not_examined"]) == (1, 1, 2, 3)
    assert summary["by_reason"]["over the size budget"] == 1 and summary["by_reason"]["file type not scanned"] == 1


# ── AC6: budget and priority ──────────────────────────────────────────────────

def test_priority_puts_infrastructure_and_security_code_first():
    paths = ["README.md", "utils/strings.py", "auth/login.py", "Dockerfile", "templates/x.html", "settings.yaml"]
    ordered = [e.path for e in sorted(classify_tree([(p, 1) for p in paths]), key=priority)]
    assert ordered[:2] == ["Dockerfile", "auth/login.py"]
    assert ordered.index("utils/strings.py") < ordered.index("templates/x.html") < ordered.index("README.md")


def test_a_repository_over_budget_gets_a_prioritised_subset_and_an_explicit_unexamined_list():
    filler = "x = 1\n" * 100_000                                    # about 600 KB across the repository
    contents = {f"pkg/mod_{i}.py": filler[:60_000] for i in range(10)}
    contents["Dockerfile"] = "FROM python:3.12\nUSER root\n"
    contents["auth/login.py"] = "def login(): pass\n"
    contents["README.md"] = "# Demo\n"
    scan = build_scan_input(contents, budget=MAX_BYTES)
    summary = summarise_manifest(scan.manifest)
    assert summary["examined"] + summary["unexamined"] == 13 and summary["unexamined"] >= 4
    assert "Dockerfile" in scan.examined and "auth/login.py" in scan.examined          # priority, not alphabet
    assert len(scan.code.encode("utf-8")) <= MAX_BYTES + 1000
    for m in scan.manifest:
        assert m["status"] in {"examined", "unexamined"} and m["reason"]
    unexamined = {m["path"] for m in scan.manifest if m["status"] == "unexamined"}
    assert unexamined and not unexamined & set(scan.examined)
    assert "remaining files skipped" not in scan.code                                   # no silent marker cut


def test_small_repositories_are_fully_examined():
    scan = build_scan_input({"a.py": "x = 1", "b.py": "y = 2", "logo.png": "binary"})
    assert scan.examined == ["a.py", "b.py"]
    assert {m["path"]: m["status"] for m in scan.manifest} == {"a.py": "examined", "b.py": "examined", "logo.png": "excluded"}
    assert scan.code.index("# ── a.py") < scan.code.index("# ── b.py")


def test_the_first_file_is_always_taken_even_if_it_alone_exceeds_the_budget():
    assert build_scan_input({"a.py": "x" * 50}, budget=10).examined == ["a.py"]


def test_user_selection_marks_the_rest_as_not_selected():
    contents = {"a.py": "x = 1", "b.py": "y = 2"}
    entries = classify_tree([("a.py", 5), ("b.py", 5)])
    scan = build_scan_input({"a.py": "x = 1"}, entries, not_selected={"b.py"})
    status = {m["path"]: (m["status"], m["reason"]) for m in scan.manifest}
    assert status["b.py"] == ("excluded", "not selected by the user") and scan.examined == ["a.py"]
    assert contents  # silence unused


def test_a_file_that_failed_to_download_is_reported_not_dropped():
    entries = classify_tree([("a.py", 5), ("b.py", 5)])
    scan = build_scan_input({"a.py": "x = 1"}, entries)
    status = {m["path"]: (m["status"], m["reason"]) for m in scan.manifest}
    assert status["b.py"] == ("unexamined", "could not be downloaded") and scan.examined == ["a.py"]


def test_readme_text_is_returned_for_business_context():
    assert build_scan_input({"README.md": "# Shop", "a.py": "x"}).readme_text == "# Shop"
    assert build_scan_input({"a.py": "x"}).readme_text == ""


def test_choose_within_budget_uses_tree_sizes_before_download():
    entries = [ScopeEntry("Dockerfile", True, "infra file", "infra", 100), ScopeEntry("a.py", True, "code file", "code", 900),
               ScopeEntry("b.py", True, "code file", "code", 900), ScopeEntry("c.md", False, "x", "doc", 5)]
    chosen, over = choose_within_budget(entries, budget=1000)
    assert [e.path for e in chosen] == ["Dockerfile", "a.py"] and [e.path for e in over] == ["b.py"]


# ── the GitHub scan carries the manifest into the pipeline ───────────────────

def test_the_github_scan_passes_the_manifest_and_counts_to_the_pipeline(monkeypatch):
    import api.routers.github as gh
    from api.main import app

    tree = classify_tree([("app.py", 10), ("Dockerfile", 10), ("logo.png", 10), ("poetry.lock", 10)])
    monkeypatch.setattr(gh, "list_repo", lambda url: (NS(owner="o", repo="r", branch="main"), tree, None))
    monkeypatch.setattr(gh, "fetch_contents", lambda ref, paths: ({p: "x = 1" for p in paths}, {}))
    captured = {}

    def fake_run(code, **kw):
        captured.update(kw)
        return {"failures": [], "risks": []}

    monkeypatch.setattr(gh, "run_fmea", fake_run)
    with TestClient(app).stream("POST", "/api/github/scan", json={"repo_url": "https://github.com/o/r"}) as r:
        body = "".join(r.iter_text())
    summary = captured["scope"]["summary"]
    assert (summary["examined"], summary["excluded"]) == (2, 2)
    assert {m["path"] for m in captured["scope"]["manifest"]} == {"app.py", "Dockerfile", "logo.png", "poetry.lock"}
    assert "2 not examined" in body


def test_user_selection_in_the_github_scan_is_recorded_as_not_selected(monkeypatch):
    import api.routers.github as gh
    from api.main import app

    tree = classify_tree([("a.py", 10), ("b.py", 10)])
    monkeypatch.setattr(gh, "list_repo", lambda url: (NS(owner="o", repo="r", branch="main"), tree, None))
    monkeypatch.setattr(gh, "fetch_contents", lambda ref, paths: ({p: "x" for p in paths}, {}))
    captured = {}
    monkeypatch.setattr(gh, "run_fmea", lambda code, **kw: captured.update(kw) or {"failures": [], "risks": []})
    with TestClient(app).stream("POST", "/api/github/scan",
                                json={"repo_url": "https://github.com/o/r", "selected_files": ["a.py"]}) as r:
        "".join(r.iter_text())
    status = {m["path"]: m["status"] for m in captured["scope"]["manifest"]}
    assert status == {"a.py": "examined", "b.py": "excluded"}
