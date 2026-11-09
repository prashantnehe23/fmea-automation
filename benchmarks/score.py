"""
benchmarks/score.py — B-026: score a scan's findings against a labelled benchmark repository.

Pure and deterministic: no LLM, no network. Matching rules are documented in
docs/decisions/ADR-023-benchmark-methodology.md.

A finding is a plain dict with (all optional) failure_mode, trigger, evidence,
business_impact, attack_chain (list or str), priority, root_cause.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

THREAT_CLASSES = frozenset({
    "injection", "authn", "authz", "secrets", "ssrf", "xss", "deserialization", "crypto",
    "data_exposure", "supply_chain", "infra_misconfig", "ci_compromise", "race_condition",
    "resource_exhaustion", "logic_flaw", "prompt_injection", "path_traversal",
})
ROOT_CAUSE_DOMAINS = frozenset({"security", "architectural", "engineering", "operational"})
HIGH_BANDS = frozenset({"High", "Critical"})

_SKIP_DIRS = {".git", "__pycache__", "node_modules"}
_CITED_PATH = re.compile(r"([\w./\\-]+\.\w+)(?::(\d+))?")


# ── Truth files ───────────────────────────────────────────────────────────────

def load_repo_files(repo_dir: Path) -> dict[str, str]:
    """Relative posix path -> text, for every file of a benchmark repository."""
    files: dict[str, str] = {}
    for p in sorted(Path(repo_dir).rglob("*")):
        if p.is_file() and not (_SKIP_DIRS & set(p.relative_to(repo_dir).parts)) and p.name != "truth.json":
            files[p.relative_to(repo_dir).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    return files


def load_truth(repo_dir: Path, require_signed_off: bool = False) -> dict:
    """Load and validate repo_dir/truth.json; raise ValueError listing every problem."""
    repo_dir = Path(repo_dir)
    data = json.loads((repo_dir / "truth.json").read_text(encoding="utf-8"))
    files = load_repo_files(repo_dir)
    errors: list[str] = []
    items = data.get("items") or []
    if not items:
        errors.append("no truth items")
    if require_signed_off and not data.get("signed_off_by"):
        errors.append("labels are not signed off (signed_off_by is empty)")
    seen: set[str] = set()
    for it in items:
        tid = it.get("id", "?")
        if tid in seen:
            errors.append(f"{tid}: duplicate id")
        seen.add(tid)
        if it.get("threat_class") not in THREAT_CLASSES:
            errors.append(f"{tid}: unknown threat_class {it.get('threat_class')!r}")
        if it.get("root_cause_domain") not in ROOT_CAUSE_DOMAINS:
            errors.append(f"{tid}: unknown root_cause_domain {it.get('root_cause_domain')!r}")
        if not isinstance(it.get("catastrophic"), bool):
            errors.append(f"{tid}: catastrophic must be true or false")
        if not it.get("keywords"):
            errors.append(f"{tid}: keywords are empty")
        if not it.get("description"):
            errors.append(f"{tid}: description is empty")
        path, lines = it.get("file"), it.get("lines") or []
        if path not in files:
            errors.append(f"{tid}: file {path!r} not in the repository")
        elif len(lines) != 2 or not 1 <= lines[0] <= lines[1] <= len(files[path].splitlines()):
            errors.append(f"{tid}: lines {lines} outside {path}")
        elif not it.get("anchor") or it["anchor"] not in "\n".join(files[path].splitlines()[lines[0] - 1:lines[1]]):
            errors.append(f"{tid}: anchor {it.get('anchor')!r} not found in {path} lines {lines}")
        errors.extend(_path_errors(tid, it, files))
    if errors:
        raise ValueError(f"{repo_dir.name}/truth.json: " + "; ".join(errors))
    return data


def _path_errors(tid: str, item: dict, files: dict[str, str]) -> list[str]:
    """The expected exploit path (entry -> sink) is required for catastrophic items, optional otherwise."""
    path = item.get("path")
    if path is None:
        return [f"{tid}: catastrophic items need an exploit path"] if item.get("catastrophic") else []
    errors = []
    for end in ("entry", "sink"):
        spot = path.get(end) or {}
        if spot.get("file") not in files:
            errors.append(f"{tid}: path {end} file {spot.get('file')!r} not in the repository")
        elif not spot.get("anchor") or spot["anchor"] not in files[spot["file"]]:
            errors.append(f"{tid}: path {end} anchor {spot.get('anchor')!r} not found in {spot['file']}")
        if not path.get(f"{end}_terms"):
            errors.append(f"{tid}: path {end}_terms are empty")
    return errors


# ── Matching ──────────────────────────────────────────────────────────────────

def _finding_text(finding: dict) -> str:
    chain = finding.get("attack_chain") or []
    chain = chain if isinstance(chain, str) else " ".join(map(str, chain))
    parts = [finding.get(k) or "" for k in ("failure_mode", "trigger", "evidence", "business_impact")]
    return " ".join([*map(str, parts), chain]).lower().replace("\\", "/")


def _strength(text: str, item: dict) -> float:
    """0 when the finding does not match the truth item, else a positive strength."""
    hits = sum(1 for k in set(item["keywords"]) if k.lower() in text)
    file_mentioned = item["file"].lower() in text
    if (file_mentioned and hits >= 1) or hits >= 2:
        return hits + (1.5 if file_mentioned else 0)
    return 0.0


def match_findings(
    findings: list[dict],
    items: list[dict],
    judge: Callable[[dict, dict], bool] | None = None,
) -> tuple[dict[str, int], list[dict]]:
    """
    One-to-one assignment truth id -> finding index. Strongest pairs first; ties by
    truth id then finding order. `judge(finding, item)` is asked about leftover pairs
    only; each verdict is returned in the log.
    """
    texts = [_finding_text(f) for f in findings]
    pairs = sorted(
        ((-_strength(t, it), it["id"], i) for i, t in enumerate(texts) for it in items),
    )
    assigned: dict[str, int] = {}
    used: set[int] = set()
    for neg, tid, i in pairs:
        if neg == 0:
            break
        if tid not in assigned and i not in used:
            assigned[tid] = i
            used.add(i)
    log: list[dict] = []
    if judge:
        for it in items:
            if it["id"] in assigned:
                continue
            for i, f in enumerate(findings):
                if i in used:
                    continue
                verdict = bool(judge(f, it))
                log.append({"truth": it["id"], "finding": i, "match": verdict})
                if verdict:
                    assigned[it["id"]] = i
                    used.add(i)
                    break
    return assigned, log


# ── Evidence validity ─────────────────────────────────────────────────────────

def evidence_valid(finding: dict, files: dict[str, str]) -> bool:
    """True when the evidence cites a repository file and any cited line is within it."""
    evidence = str(finding.get("evidence") or "").replace("\\", "/")
    by_name = {Path(p).name: p for p in files}
    for path, line in _CITED_PATH.findall(evidence):
        key = path if path in files else by_name.get(Path(path).name)
        if key is None:
            continue
        if line and not 1 <= int(line) <= len(files[key].splitlines()):
            continue
        return True
    return False


# ── Scoring ───────────────────────────────────────────────────────────────────

def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def traces_path(finding: dict, item: dict) -> bool:
    """True when the finding's text names both the labelled entry and the labelled sink."""
    text, path = _finding_text(finding), item["path"]
    return (any(t.lower() in text for t in path["entry_terms"])
            and any(t.lower() in text for t in path["sink_terms"]))


def score_scan(
    findings: list[dict],
    truth: dict,
    files: dict[str, str],
    judge: Callable[[dict, dict], bool] | None = None,
) -> dict:
    items = truth["items"]
    by_id = {it["id"]: it for it in items}
    assigned, judge_log = match_findings(findings, items, judge)
    matched_idx = set(assigned.values())
    catastrophic = [it["id"] for it in items if it["catastrophic"]]
    caught_cat = [t for t in catastrophic if t in assigned]
    placed = [t for t in caught_cat if findings[assigned[t]].get("priority") in HIGH_BANDS]
    with_path = [t for t in assigned if by_id[t].get("path")]
    traced = [t for t in with_path if traces_path(findings[assigned[t]], by_id[t])]
    with_rc = [t for t in assigned if findings[assigned[t]].get("root_cause")]
    rc_agree = [t for t in with_rc if findings[assigned[t]]["root_cause"] == by_id[t]["root_cause_domain"]]
    return {
        "repo": truth.get("repo"),
        "counts": {
            "truth": len(items), "findings": len(findings), "matched": len(assigned),
            "matched_findings": len(matched_idx),
            "catastrophic": len(catastrophic), "caught_catastrophic": len(caught_cat), "placed": len(placed),
            "with_path": len(with_path), "traced": len(traced),
            "valid_evidence": sum(evidence_valid(f, files) for f in findings),
        },
        "recall": _ratio(len(assigned), len(items)),
        "precision": _ratio(len(matched_idx), len(findings)),
        "catastrophic_recall": _ratio(len(caught_cat), len(catastrophic)),
        "placement": _ratio(len(placed), len(caught_cat)),
        "evidence_validity": _ratio(sum(evidence_valid(f, files) for f in findings), len(findings)),
        "root_cause_agreement": _ratio(len(rc_agree), len(with_rc)),
        "path_accuracy": _ratio(len(traced), len(with_path)),
        "path_untraced": sorted(set(with_path) - set(traced)),
        "found": sorted(assigned),
        "missed": sorted(set(by_id) - set(assigned)),
        "missed_catastrophic": sorted(set(catastrophic) - set(assigned)),
        "false_positives": [
            findings[i].get("failure_mode", f"finding {i}")
            for i in range(len(findings)) if i not in matched_idx
        ],
        "judge_log": judge_log,
    }


def stability(runs: list[dict]) -> float | None:
    """Share of truth items found in any run that were found in every run."""
    found = [set(r["found"]) for r in runs]
    in_any = set.union(*found) if found else set()
    return _ratio(len(set.intersection(*found)), len(in_any)) if in_any else None
