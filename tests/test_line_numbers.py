"""
tests/test_line_numbers.py — B-041: agents see numbered code; line accuracy is measured

  AC1  every code line is numbered per file, restarting at each file header
  AC2  the agents receive numbered code; the original text is untouched
  AC3  cited lines are parsed in the forms models use, and checked against the labelled lines
  AC4  the stored/cached/chat text is not numbered
"""

import pytest

from benchmarks.score import cited_lines, cites_labelled_lines, load_repo_files, load_truth, score_scan
from core.github_fetcher import file_block
from core.line_numbers import MARKER, number_lines
from core.chat import split_code_blob
from benchmarks import run

A = "import os\n\nx = 1\n"
B = "def f():\n    return 2"


def blob():
    return "\n\n".join([file_block("a.py", A), file_block("src/b.py", B)])


# ── AC1 ───────────────────────────────────────────────────────────────────────

def test_lines_are_numbered_and_restart_per_file():
    out = number_lines(blob())
    lines = out.split("\n")
    assert lines[0] == MARKER
    a = lines.index(next(l for l in lines if l.startswith("# ── a.py")))
    assert lines[a + 1:a + 4] == ["1| import os", "2| ", "3| x = 1"]
    b = lines.index(next(l for l in lines if l.startswith("# ── src/b.py")))
    assert lines[b + 1:b + 3] == ["1| def f():", "2|     return 2"]


def test_blank_lines_between_files_are_not_numbered_as_code():
    out = number_lines(blob()).split("\n")
    b = next(i for i, l in enumerate(out) if l.startswith("# ── src/b.py"))
    assert not any("| " in l and l.split("|")[0].isdigit() for l in out[b - 2:b])


def test_a_comment_that_looks_like_a_header_inside_code_does_not_restart_numbering():
    code = file_block("a.py", "x = 1\n# ── Helpers ──\ny = 2")
    out = number_lines(code).split("\n")
    assert "2| # ── Helpers ──" in out and "3| y = 2" in out          # not path-like, so not a header


def test_pasted_code_without_headers_is_numbered_from_one():
    out = number_lines("a = 1\nb = 2").split("\n")
    assert out[2:] == ["1| a = 1", "2| b = 2"]


def test_empty_code_does_not_crash():
    assert number_lines("").startswith(MARKER)


# ── AC2 / AC4 ─────────────────────────────────────────────────────────────────

def test_the_pipeline_sends_numbered_code_to_the_agents(monkeypatch):
    import workflows.fmea_pipeline as pipeline
    seen = {}

    class Stop(Exception):
        pass

    def capture(name):
        def fake(code, *args, **kwargs):
            seen[name] = code
            if name == "saboteur":
                raise Stop()
            return None
        return fake

    monkeypatch.setattr(pipeline, "run_surveyor", capture("surveyor"))
    monkeypatch.setattr(pipeline, "run_saboteur", capture("saboteur"))
    original = blob()
    with pytest.raises(Stop):
        pipeline.run_fmea(original, force_rerun=True)
    assert seen["surveyor"] == seen["saboteur"] == number_lines(original)
    assert "1| import os" in seen["surveyor"] and original.count("| ") == 0       # input text itself untouched


def test_the_text_stored_for_the_chat_is_not_numbered():
    files = split_code_blob(blob(), known_paths=["a.py", "src/b.py"])
    assert files["a.py"] == A.strip("\n") and "1|" not in files["src/b.py"]


def test_benchmark_scan_input_is_unnumbered_so_the_pipeline_numbers_it_once():
    code, _ = run.scan_input(run.REPOS_DIR / "shop-api")
    assert MARKER not in code and "\n1| " not in code


# ── AC3 ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("evidence, expected", [
    ("app.py:32 f-string", [(32, 32)]),
    ("app.py:25-27 something", [(25, 27)]),
    ("app.py:25–27", [(25, 27)]),                       # en dash
    ("see app.py (lines 25-27)", [(25, 27)]),
    ("app.py line 9 and app.py, lines 12-14", [(9, 9), (12, 14)]),
    ("src/app.py#L40", [(40, 40)]),
    ("config.py:2 and app.py:7", [(7, 7)]),             # only the requested file
    ("no citation at all", []),
    ("app.py is mentioned without a line", []),
    (None, []),
])
def test_cited_lines_forms(evidence, expected):
    assert cited_lines(evidence, "app.py") == expected


def test_windows_separators_are_handled():
    assert cited_lines(r"src\app.py:5", "app.py") == [(5, 5)]


ITEM = {"file": "app.py", "lines": [31, 33]}


@pytest.mark.parametrize("evidence, ok", [
    ("app.py:32", True), ("app.py:31-33", True), ("app.py:28", True), ("app.py:36", True),    # within +/- 3
    ("app.py:25-27", False),                       # the real off-by-six seen in the baseline
    ("app.py:37", False), ("config.py:32", False), ("", False),
    ("app.py:10-40", True),                        # a range that spans the label overlaps it
])
def test_cites_labelled_lines(evidence, ok):
    assert cites_labelled_lines({"evidence": evidence}, ITEM) is ok


def test_line_accuracy_in_the_score():
    repo = run.REPOS_DIR / "shop-api"
    truth, files = load_truth(repo), load_repo_files(repo)
    right = {"failure_mode": "SQL injection", "trigger": "/orders/search",
             "evidence": "app.py:32 f-string reaches db().execute", "priority": "High"}
    wrong = {"failure_mode": "Hardcoded JWT secret", "evidence": "config.py:9 JWT_SECRET", "priority": "High"}
    s = score_scan([right, wrong], truth, files)
    assert s["counts"]["matched"] == 2 and s["counts"]["line_on_target"] == 1 and s["line_accuracy"] == 0.5
    assert score_scan([], truth, files)["line_accuracy"] is None
