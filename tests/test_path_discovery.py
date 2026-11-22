"""
B-028 phase B (ADR-015, ADR-032): hunt exploit paths across components, verify each against the code, and feed the verified
ones into the normal pipeline as findings.

  AC  the hunt reads connected files together and is told to follow requests across components
  AC  a path whose quoted code is not in the files is refuted without a model call; wrong line numbers are corrected
  AC  a path the verifier refutes is not reported; uncertain ones are kept and marked
  AC  verified paths become findings with their steps; counts and uncovered files are reported
  AC  a provider block or spend limit is never swallowed
"""

import json

import pytest

from agents import path_hunter, path_verifier
from core import path_discovery
from core.models import ExploitPath, FailureMode, PathStep
from core.provider_block import ProviderBlocked

HANDLERS = ("def upload(request):\n    check = VALIDATORS.get(request.path)\n    return save(request.body)\n\n"
            "def get_endpoints(pick):\n    return [('/upload', upload)]\n")
AUTH = ("from server.handlers import get_endpoints\n\ndef allow_all():\n    return True\n\n"
        "VALIDATORS = {p: h for p, h, m in get_endpoints(lambda c: allow_all)}\n")
FILES = {"server/handlers.py": HANDLERS, "server/auth.py": AUTH}


def raw_path(**kw):
    base = {"title": "Upload validator is the handler itself", "entry_point": "POST /upload",
            "steps": [{"file": "server/auth.py", "lines": "6", "action": "validator table is built from get_endpoints",
                       "quote": "VALIDATORS = {p: h for p, h, m in get_endpoints(lambda c: allow_all)}"},
                      {"file": "server/handlers.py", "lines": "2", "action": "handler looks up a validator but never calls it",
                       "quote": "check = VALIDATORS.get(request.path)"}],
            "broken_check": "the permission check never denies", "exploit": "any logged-in user uploads", "impact": "unauthorised write"}
    return {**base, **kw}


# ── the hunt ──────────────────────────────────────────────────────────────────

def test_the_hunt_prompt_shows_the_connected_files_and_asks_for_cross_component_paths_without_hints():
    prompt = path_hunter.build_hunt_prompt(FILES, "server/auth.py -> server/handlers.py (1 call)")
    assert "server/auth.py" in prompt and "VALIDATORS" in prompt and "server/auth.py -> server/handlers.py" in prompt
    low = prompt.lower()
    assert "across" in low and "component" in low and "entry point" in low
    for hint in ("email_verified", "hosted_domain", "startswith", "validate_gateway_proxy", "zip"):
        assert hint not in low


def test_hunted_paths_are_parsed_tolerantly_and_cut_off_replies_keep_complete_items():
    broken = json.dumps([raw_path(), raw_path(title="Second")])[:-40]          # the reply is cut inside the last item
    paths = path_hunter.parse_paths(broken)
    assert [p.title for p in paths] == ["Upload validator is the handler itself"]
    odd = path_hunter.parse_paths(json.dumps([{"title": "No steps"}, "junk", raw_path(steps="a string")]))
    assert all(isinstance(p, ExploitPath) for p in odd) and odd[0].steps == []


def test_a_hunt_answers_with_paths_and_swallows_nothing_it_should_not():
    asked = []
    paths = path_hunter.run_path_hunter(FILES, "map", ask=lambda prompt, n: asked.append(prompt) or json.dumps([raw_path()]))
    assert len(paths) == 1 and paths[0].steps[0].file == "server/auth.py" and len(asked) == 1

    def blocked(prompt, n):
        raise ProviderBlocked("mistral", "m", "paths")
    with pytest.raises(ProviderBlocked):
        path_hunter.run_path_hunter(FILES, "map", ask=blocked)
    assert path_hunter.run_path_hunter(FILES, "map", ask=lambda p, n: "I cannot answer") == []


# ── verification ──────────────────────────────────────────────────────────────

def test_quotes_are_found_whatever_the_whitespace_and_line_numbers_are_corrected():
    path = ExploitPath(**raw_path(steps=[{"file": "server/auth.py", "lines": "99", "quote": "VALIDATORS  =  {p: h for p, h, m in\n get_endpoints(lambda c: allow_all)}"}]))
    fixed, missing = path_verifier.check_evidence(path, FILES)
    assert missing == 0 and fixed.steps[0].lines == "6"


def test_a_quote_that_is_not_in_the_file_is_counted_as_missing():
    path = ExploitPath(**raw_path(steps=[{"file": "server/auth.py", "lines": "1", "quote": "def totally_invented():"},
                                         {"file": "server/nowhere.py", "lines": "1", "quote": "x"}]))
    _, missing = path_verifier.check_evidence(path, FILES)
    assert missing == 2


def test_a_path_with_invented_code_is_refuted_without_asking_a_model():
    path = ExploitPath(**raw_path(steps=[{"file": "server/auth.py", "lines": "1", "quote": "def totally_invented():"}]))

    def never(prompt, n):
        raise AssertionError("no model call expected")
    out = path_verifier.verify_path(path, FILES, ask=never)
    assert out.status == "refuted" and "not found" in out.verification


@pytest.mark.parametrize("verdict,status", [("confirmed", "confirmed"), ("refuted", "refuted"), ("uncertain", "uncertain"), ("maybe", "uncertain")])
def test_the_verifiers_verdict_sets_the_status(verdict, status):
    path = ExploitPath(**raw_path())
    out = path_verifier.verify_path(path, FILES, ask=lambda p, n: json.dumps({"verdict": verdict, "reason": "because"}))
    assert out.status == status and out.verification == "because"


def test_an_unreadable_verdict_is_uncertain_not_confirmed():
    out = path_verifier.verify_path(ExploitPath(**raw_path()), FILES, ask=lambda p, n: "looks fine to me")
    assert out.status == "uncertain"


def test_the_verifier_is_shown_the_cited_code_and_the_claim_and_asked_to_look_for_defences():
    seen = []
    path_verifier.verify_path(ExploitPath(**raw_path()), FILES, ask=lambda p, n: seen.append(p) or '{"verdict": "confirmed", "reason": "r"}')
    prompt = seen[0]
    assert "get_endpoints" in prompt and "the permission check never denies" in prompt and "defence" in prompt.lower()


# ── the whole discovery ───────────────────────────────────────────────────────

def scripted(responses_by_marker):
    def ask(prompt, n):
        for marker, reply in responses_by_marker.items():
            if marker in prompt:
                return reply if isinstance(reply, str) else json.dumps(reply)
        raise AssertionError("unexpected prompt: " + prompt[:120])
    return ask


def test_discovery_hunts_packets_verifies_paths_and_reports_counts_and_uncovered_files():
    files = {**FILES, "docs/notes.go": "package x\n"}
    ask = scripted({"Find exploit paths": [raw_path(), raw_path(title="Invented", steps=[{"file": "server/auth.py", "lines": "1", "quote": "def invented():"}])],
                    "Does this attack path work": {"verdict": "confirmed", "reason": "validator never denies"}})
    result = path_discovery.discover_exploit_paths(files, ask=ask)
    assert [p.title for p in result.confirmed()] == ["Upload validator is the handler itself"]
    assert result.counts == {"packets": 1, "found": 2, "confirmed": 1, "refuted": 1, "uncertain": 0}
    assert result.uncovered == ["docs/notes.go"] and result.packet_of[path_discovery._key(result.confirmed()[0])] == 0


def test_the_same_path_found_in_two_packets_is_reported_once():
    files = {"a/auth.py": AUTH, "a/handlers.py": HANDLERS, "b/auth.py": AUTH, "b/handlers.py": HANDLERS}
    ask = scripted({"Find exploit paths": [raw_path()], "Does this attack path work": {"verdict": "confirmed", "reason": "r"}})
    result = path_discovery.discover_exploit_paths(files, ask=ask, budget_bytes=len(HANDLERS) + len(AUTH) + 10)
    assert len(result.paths) == 1


def test_uncertain_paths_are_kept_but_marked_and_refuted_ones_are_not_findings():
    ask = scripted({"Find exploit paths": [raw_path(), raw_path(title="Another")],
                    "Does this attack path work": {"verdict": "uncertain", "reason": "depends on config"}})
    result = path_discovery.discover_exploit_paths(FILES, ask=ask)
    findings = path_discovery.paths_to_failures(result.reportable())
    assert len(findings) == 2 and all(f.path_status == "uncertain" for f in findings)


def test_a_verified_path_becomes_a_finding_with_evidence_and_the_steps():
    path = ExploitPath(**raw_path(), status="confirmed", verification="validator never denies")
    fixed, _ = path_verifier.check_evidence(path, FILES)
    finding, = path_discovery.paths_to_failures([fixed])
    assert isinstance(finding, FailureMode) and finding.failure_mode == "Upload validator is the handler itself"
    assert finding.evidence.startswith("server/auth.py:6") and "VALIDATORS" in finding.evidence
    assert finding.attack_chain[0].startswith("POST /upload") and any("server/handlers.py:2" in step for step in finding.attack_chain)
    assert finding.attack_chain[-1] == "Fails here: the permission check never denies"
    assert finding.exploit_path[0].file == "server/auth.py" and finding.path_status == "confirmed"
    assert "unauthorised write" in finding.business_impact and "any logged-in user uploads" in finding.trigger


def test_a_provider_block_in_a_hunt_or_a_verification_reaches_the_caller():
    def blocked(prompt, n):
        raise ProviderBlocked("mistral", "m", "paths")
    with pytest.raises(ProviderBlocked):
        path_discovery.discover_exploit_paths(FILES, ask=blocked)
    ask = scripted({"Find exploit paths": [raw_path()]})
    ask_then_block = lambda p, n: ask(p, n) if "Find exploit paths" in p else blocked(p, n)
    with pytest.raises(ProviderBlocked):
        path_discovery.discover_exploit_paths(FILES, ask=ask_then_block)


# ── in the pipeline ───────────────────────────────────────────────────────────

def _harness(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, "tests")
    from test_finding_lifecycle import Harness
    import workflows.fmea_pipeline as pipeline
    from core.models import RootCause
    h = Harness(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline, "run_root_cause_analyst", lambda f, c: [RootCause(failure_mode=x.failure_mode) for x in f])
    return h, pipeline


def _code():
    from core.github_fetcher import file_block
    return "\n\n".join(file_block(p, t) for p, t in FILES.items())


def _discovery(statuses=("confirmed", "refuted", "uncertain")):
    d = path_discovery.PathDiscovery(packet_files=[["server/auth.py", "server/handlers.py"]], uncovered=["worker/main.go"])
    for i, status in enumerate(statuses):
        d.paths.append(ExploitPath(**raw_path(title=f"Path {i}"), status=status, verification="v"))
        d.packet_of[path_discovery._key(d.paths[-1])] = 0
    return d


def test_path_mode_replaces_the_brainstorm_and_feeds_verified_paths_through_the_normal_stages(monkeypatch, tmp_path):
    h, pipeline = _harness(monkeypatch, tmp_path)
    seen = {}
    monkeypatch.setattr(pipeline, "discover_exploit_paths", lambda files, **kw: seen.update(files=files) or _discovery())
    h.next_failures = [FailureMode(failure_mode="From the brainstorm", attack_chain=["x"], business_impact="b", blast_radius="c", trigger="t")]
    result = pipeline.run_fmea(_code(), workspace=__import__("test_finding_lifecycle").WS, force_rerun=True, discovery="paths")
    assert sorted(seen["files"]) == ["server/auth.py", "server/handlers.py"]            # the code blob is split back into files
    names = [f.failure_mode for f in result["failures"]]
    assert names == ["Path 0", "Path 2"]                                                  # confirmed and uncertain; refuted is dropped; no brainstorm
    assert [f.path_status for f in result["failures"]] == ["confirmed", "uncertain"]
    assert result["failures"][0].exploit_path and len(result["risks"]) == 2 and len(result["remediations"]) == 2
    assert result["discovery"] == {"mode": "paths", "packets": 1, "found": 3, "confirmed": 1, "refuted": 1, "uncertain": 1, "uncovered": ["worker/main.go"]}


def test_the_default_mode_is_unchanged_and_says_so(monkeypatch, tmp_path):
    h, pipeline = _harness(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline, "discover_exploit_paths", lambda *a, **k: (_ for _ in ()).throw(AssertionError("not in this mode")))
    h.next_failures = [FailureMode(failure_mode="From the brainstorm", attack_chain=["x"], business_impact="b", blast_radius="c", trigger="t")]
    result = pipeline.run_fmea(_code(), workspace=__import__("test_finding_lifecycle").WS, force_rerun=True)
    assert [f.failure_mode for f in result["failures"]] == ["From the brainstorm"] and result["discovery"] == {"mode": "scenarios"}


def test_a_project_with_nothing_to_hunt_falls_back_to_the_brainstorm_and_says_so(monkeypatch, tmp_path):
    h, pipeline = _harness(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline, "discover_exploit_paths", lambda files, **kw: path_discovery.PathDiscovery(uncovered=["a.go"]))
    h.next_failures = [FailureMode(failure_mode="From the brainstorm", attack_chain=["x"], business_impact="b", blast_radius="c", trigger="t")]
    result = pipeline.run_fmea(_code(), workspace=__import__("test_finding_lifecycle").WS, force_rerun=True, discovery="paths")
    assert [f.failure_mode for f in result["failures"]] == ["From the brainstorm"]
    assert result["discovery"]["mode"] == "scenarios" and "no entry points" in result["discovery"]["note"]


def test_the_scan_requests_accept_only_the_two_modes():
    from api.schemas import ScanRequest
    from api.routers.github import GithubScanRequest
    assert ScanRequest(code="x").discovery == "scenarios" and GithubScanRequest(repo_url="https://github.com/a/b").discovery == "scenarios"
    assert ScanRequest(code="x", discovery="paths").discovery == "paths"
    for model, kw in ((ScanRequest, {"code": "x"}), (GithubScanRequest, {"repo_url": "https://github.com/a/b"})):
        with pytest.raises(ValueError):
            model(**kw, discovery="everything")


# ── review fixes (independent review, 2026-11-22) ─────────────────────────────

def test_a_short_quote_is_not_evidence_and_a_partly_invented_path_is_never_confirmed():
    assert path_verifier.locate("return", "def f():" + chr(10) + "    return 1") is None
    path = ExploitPath(**raw_path(steps=raw_path()["steps"] + [{"file": "server/auth.py", "lines": "1", "quote": "def totally_invented_helper():"}]))
    out = path_verifier.verify_path(path, FILES, ask=lambda p, n: json.dumps({"verdict": "confirmed", "reason": "ok"}))
    assert out.status == "uncertain" and "not found" in out.verification and out.steps[0].lines
    assert [s.lines for s in out.steps][2:] == [""]                 # unverified steps keep no line numbers, so they are never evidence
    assert path_discovery.paths_to_failures([out])[0].evidence.startswith("server/auth.py:6")


def test_a_failed_call_loses_only_its_own_packet_or_path_and_is_listed():
    calls = {"n": 0}

    def flaky(prompt, n):
        if "Find exploit paths" in prompt:
            calls["n"] += 1
            raise RuntimeError("timeout")
        raise AssertionError("nothing to verify")
    result = path_discovery.discover_exploit_paths(FILES, ask=flaky)
    assert result.paths == [] and sorted(result.uncovered) == sorted(FILES)
    ask = scripted({"Find exploit paths": [raw_path()]})
    result = path_discovery.discover_exploit_paths(FILES, ask=lambda p, n: ask(p, n) if "Find exploit paths" in p else (_ for _ in ()).throw(RuntimeError("boom")))
    assert [p.status for p in result.paths] == ["uncertain"] and "could not run" in result.paths[0].verification


def test_two_paths_with_one_title_are_assessed_against_their_own_packet():
    a = ExploitPath(**raw_path(entry_point="POST /a")); b = ExploitPath(**raw_path(entry_point="POST /b"))
    assert path_discovery._key(a) != path_discovery._key(b)


def test_a_path_scan_does_not_use_the_code_keyed_cache_or_mark_locked_findings_not_seen(monkeypatch, tmp_path):
    h, pipeline = _harness(monkeypatch, tmp_path)
    ws = __import__("test_finding_lifecycle").WS
    h.next_failures = [FailureMode(failure_mode="From the brainstorm", attack_chain=["x"], business_impact="b", blast_radius="c", trigger="t")]
    first = pipeline.run_fmea(_code(), workspace=ws)                       # a normal scan fills the cache
    monkeypatch.setattr(pipeline, "discover_exploit_paths", lambda files, **kw: _discovery(("confirmed",)))
    paths = pipeline.run_fmea(_code(), workspace=ws, discovery="paths")   # no force_rerun: must still run the path workflow
    assert not paths.get("from_cache") and paths["discovery"]["mode"] == "paths"
    assert paths["lifecycle_changes"] == {}
    again = pipeline.run_fmea(_code(), workspace=ws)
    assert [f.failure_mode for f in again["failures"]] == [f.failure_mode for f in first["failures"]]   # the paths result was not cached
