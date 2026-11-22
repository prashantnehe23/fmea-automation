"""
core/pr_check.py — B-012 (ADR-029): the verdict for one pull request.

The pull request's head is scanned in one quick pass (changed files first) without touching the project's
record: the registry, its history, the scan log and the caches stay as the default branch left them. The
findings are compared with that record: a finding the project already knows is not reported again; one it
does not know is new; one that was marked fixed and is back is regressed. The check fails on a new or
regressed finding at or above the project's severity threshold, and stops at its USD budget.
"""

from __future__ import annotations

import re
import threading
import urllib.parse

import memory.db as db
from core import budget
from core.findings import finding_identity
from core.github_fetcher import RepoAccessError, fetch_contents, fetch_pr_changes, list_repo
from core.scan_scope import MAX_BYTES, build_scan_input, plan_batches, summarise_manifest
from core.untrusted import sanitize_text
from core.workspace import WorkspaceContext
from workflows.fmea_pipeline import run_fmea

_LOCATION = re.compile(r"([\w./\\-]+\.\w{1,8}):(\d+)")
MAX_CONCURRENT_PER_PROJECT = 2          # checks running at once for one project: each may spend its whole budget
_active: dict[int, int] = {}
_active_lock = threading.Lock()


class PrCheckError(Exception):
    """The check could not run; `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _location(evidence: str | None) -> tuple[str | None, int | None]:
    m = _LOCATION.search(evidence or "")
    return (m.group(1).replace("\\", "/"), int(m.group(2))) if m else (None, None)


def _md(text: str | None, limit: int = 160) -> str:
    """Model text made safe to post as a comment: no mentions, links, images, HTML or markdown, bounded length."""
    flat = re.sub(r"<[^>]*>", " ", " ".join(str(text or "").split()))
    flat = flat.replace("@", "@\u200b")                                  # a zero-width space defuses @mentions
    flat = re.sub(r"([\\`*_\[\]()#!|~<>])", r"\\\1", flat)
    flat = re.sub(r"https?://", "", flat, flags=re.IGNORECASE)
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _known_elsewhere(f, snapshot_failures: list[dict]) -> bool:
    """Is this head finding one the default branch's last scan already had, under another name or place?
    Same code quote, or the same file with a similar name. Guards against blocking a merge on a renamed old finding."""
    key, (path, _) = finding_identity(f.evidence), _location(f.evidence)
    words = set(re.findall(r"[a-z0-9]+", f.failure_mode.lower()))
    for old in snapshot_failures:
        old_key = finding_identity(old.get("evidence"))
        if key and old_key and key == old_key:
            return True
        old_path, _ = _location(old.get("evidence"))
        old_words = set(re.findall(r"[a-z0-9]+", str(old.get("failure_mode", "")).lower()))
        if path and old_path == path and words and old_words and len(words & old_words) / len(words | old_words) >= 0.5:
            return True
    return False


DIFF_MARGIN = 3        # lines around a changed range that still count as touched by the pull request


def _in_diff(item: dict, changes: dict) -> bool:
    """Does a finding sit in code the pull request changed? Without diff information everything counts."""
    if not changes or not item["file"] or not item["line"]:
        return True
    key = next((p for p in changes if p == item["file"] or p.endswith("/" + item["file"]) or item["file"].endswith("/" + p)), None)
    if key is None:
        return False
    ranges = changes[key]
    return ranges is None or any(a - DIFF_MARGIN <= item["line"] <= b + DIFF_MARGIN for a, b in ranges)


def _finding(f, risk, owner: str, repo: str, sha: str) -> dict:
    path, line = _location(f.evidence)
    url = (f"https://github.com/{owner}/{repo}/blob/{urllib.parse.quote(sha)}/{urllib.parse.quote(path)}#L{line}"
           if path and line else None)
    return {"failure_mode": f.failure_mode, "severity": risk.severity, "occurrence": risk.occurrence,
            "detection": risk.detection, "rpn": risk.rpn, "priority": risk.priority, "impact": f.business_impact,
            "evidence": f.evidence, "file": path, "line": line, "url": url}


def _row(item: dict) -> str:
    where = f"[`{item['file']}:{item['line']}`]({item['url']})" if item["url"] else "location not cited"
    return f"- **{_md(item['failure_mode'], 100)}** (severity {item['severity']}, RPN {item['rpn']}) at {where}: {_md(item['impact'])}"


def _comment(out: dict) -> str:
    blocks = []
    for title, items in (("New findings", out["new"]), ("Findings that came back after being fixed", out["regressed"])):
        if items:
            blocks.append(f"**{title}**\n" + "\n".join(_row(i) for i in items))
    if out["notices"]:
        blocks.append("**Notes**\n" + "\n".join(f"- {n}" for n in out["notices"]))
    if out["budget_reached"]:
        blocks.append(f"The check's budget of ${out['budget_usd']:.2f} was reached"
                      + (": the findings above are partial." if blocks else " before the code could be fully examined, so it passes without a verdict on the code."))
    if not blocks:
        return ""
    head = "### FMEA check: " + ("failed" if out["verdict"] == "fail" else "passed" if (out["new"] or out["regressed"]) else "notes")
    foot = (f"_Examined {out['examined']} files, {out['not_examined']} not examined. "
            f"Cost ${out['cost_usd']:.2f} of ${out['budget_usd']:.2f}._")
    return "\n\n".join([head, *blocks, foot])


def _result(verdict: str, summary: str, **extra) -> dict:
    base = {"verdict": verdict, "summary": summary, "new": [], "regressed": [], "notices": [], "outside_changes": 0, "comment_markdown": "",
            "budget_reached": False, "budget_usd": None, "cost_usd": 0.0, "examined": 0, "not_examined": 0}
    return {**base, **extra}


def run_pr_check(owner: str, repo: str, head_sha: str, pr_number: int | None = None,
                 budget_usd: float | None = None) -> dict:
    project = db.find_project_by_repo(owner, repo)
    if project is None:
        raise PrCheckError(f"No project is linked to github.com/{owner}/{repo}. Add the repository to a project first.", 404)
    config = db.get_pr_check_config(project["id"])
    # The project's budget is the ceiling: a request may ask for less, never more
    limit = float(min(budget_usd, config["budget_usd"]) if budget_usd is not None else config["budget_usd"])
    if not config["enabled"]:
        return _result("pass", "The pull-request check is disabled for this project.", budget_usd=limit)
    baseline = db.get_locked_scenarios(project["workspace_id"]) if project["workspace_id"] else []
    if not baseline:
        message = ("No baseline yet: scan the default branch of this project once so that new findings can be told from "
                   "existing ones. Until then this check cannot report anything.")
        out = _result("pass", message, budget_usd=limit, notices=[message])
        out["comment_markdown"] = _comment(out)
        return out
    states = {r["failure_mode"]: r.get("state", "confirmed") for r in baseline}
    snapshot = db.get_latest_snapshot(project["workspace_id"])
    known = ((snapshot or {}).get("findings") or {}).get("failures") or []
    with _active_lock:
        if _active.get(project["id"], 0) >= MAX_CONCURRENT_PER_PROJECT:
            raise PrCheckError("Checks for this project are already running; try again when one has finished.", 429)
        _active[project["id"]] = _active.get(project["id"], 0) + 1
    try:
        return _run(owner, repo, head_sha, pr_number, project, config, limit, states, known)
    finally:
        with _active_lock:
            _active[project["id"]] -= 1


def _run(owner, repo, head_sha, pr_number, project, config, limit, states, known) -> dict:

    try:
        _, entries, _ = list_repo(f"https://github.com/{owner}/{repo}/tree/{head_sha}")
        try:
            changes = fetch_pr_changes(owner, repo, pr_number) if pr_number else {}
        except Exception:
            changes = {}                                      # without the diff every finding is reported
        changed = set(changes)
        included = [e for e in entries if e.included]
        planned, _ = plan_batches(included, MAX_BYTES, 1, boost=changed)
        ref = _ref(owner, repo, head_sha)
        contents, _errors = fetch_contents(ref, [e.path for b in planned for e in b])
    except RepoAccessError as exc:
        raise PrCheckError(exc.message, 502) from exc
    scan_input = build_scan_input(contents, entries, max_batches=1, boost=changed)
    scope = {"manifest": scan_input.manifest, "summary": summarise_manifest(scan_input.manifest),
             "secrets": scan_input.secret_findings}
    skipped = [m for m in scan_input.manifest if m["path"] in changed and m["status"] != "examined"]
    workspace = WorkspaceContext(
        customer=project["portfolio_name"], project=project["name"], function="",
        business_tier=project["business_tier"], user_type=project["user_type"],
        business_context=sanitize_text(scan_input.readme_text, 2000) if scan_input.readme_text else "",
        customer_learning=False)

    result = None
    with budget.spend_limit(limit) as tracker:
        try:
            result = run_fmea(scan_input.code, max_failure_modes=None, force_rerun=True, workspace=workspace,
                              scope=scope, persist=False)
        except budget.BudgetReached:
            result = None
    out = _result("pass", "", budget_usd=limit, cost_usd=round(tracker.spent_usd, 4), budget_reached=tracker.reached,
                  examined=scope["summary"]["examined"], not_examined=scope["summary"]["not_examined"])
    if skipped:
        shown = ", ".join(f"`{_md(m['path'], 60)}` ({m['reason']})" for m in skipped[:5])
        out["notices"].append(f"{len(skipped)} file(s) changed by this pull request were not examined: {shown}"
                              + (", …" if len(skipped) > 5 else "") + ".")
    if result is None:
        out["summary"] = f"Budget reached (${limit:.2f}) before the check could finish: passing without a verdict on the code."
        out["comment_markdown"] = _comment(out)
        return out

    risks = {r.failure_mode: r for r in result["risks"]}
    by_name = {f.failure_mode: f for f in result["failures"]}
    new_names = [n for n in result["new_scenarios"] if n in by_name and not _known_elsewhere(by_name[n], known)]
    regressed_names = [n for n in by_name if states.get(n) == "fixed"]
    candidates_new = [_finding(by_name[n], risks[n], owner, repo, head_sha) for n in new_names if n in by_name and n in risks]
    candidates_regressed = [_finding(by_name[n], risks[n], owner, repo, head_sha) for n in regressed_names if n in risks]
    # A model reads the whole head and finds things the baseline run did not mention under that name. Only
    # findings in code this pull request touched are the pull request's: the rest are counted, not reported.
    out["new"] = [i for i in candidates_new if _in_diff(i, changes)]
    out["regressed"] = [i for i in candidates_regressed if _in_diff(i, changes)]
    out["outside_changes"] = len(candidates_new) + len(candidates_regressed) - len(out["new"]) - len(out["regressed"])
    blocking = [i for i in out["new"] + out["regressed"] if i["severity"] >= config["fail_severity"]]
    out["verdict"] = "fail" if blocking else "pass"
    if blocking:
        out["summary"] = f"{len(blocking)} new or regressed finding(s) at severity {config['fail_severity']} or above."
    elif out["new"] or out["regressed"]:
        out["summary"] = "New or regressed findings below the failure threshold."
    else:
        out["summary"] = "No new or regressed findings."
    if out["outside_changes"]:
        out["summary"] += f" {out['outside_changes']} other new-looking finding(s) outside the changed lines were not reported."
    if tracker.reached:
        out["summary"] += " Budget reached: the result may be incomplete."
    out["comment_markdown"] = _comment(out)
    return out


def _ref(owner: str, repo: str, sha: str):
    from core.github_fetcher import RepoRef
    return RepoRef(owner=owner, repo=repo, branch=sha)
