"""
core/sarif.py — B-045 (ADR-028): read SARIF 2.1.0 into findings, merge them with ours, and write our results as SARIF.

A SARIF file is untrusted input: size and result limits, standard JSON parsing only, artifact URIs are never
fetched, paths are made relative, every field is type-checked, and every piece of text is sanitised and bounded
(`core/untrusted.py`: hidden characters, HTML comments and tags removed). Sanitising does not make plain-text
instructions harmless; imported findings are shown with their source and the agents that read them treat
finding text as data, but this is a residual risk, recorded in ADR-028.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from core.cwe import UNMAPPED, first_cwe, normalise_cwe
from core.findings import finding_identity
from core.models import FailureMode
from core.untrusted import sanitize_text

MAX_BYTES = 10 * 1024 * 1024
MAX_RESULTS = 5000
MAX_TAGS = 50
LINE_SLACK = 3                      # lines apart that still count as the same place
SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json"


class SarifError(ValueError):
    """The file is not usable SARIF 2.1.0. The message says why, in words for the user."""


@dataclass
class ImportedFinding:
    failure: FailureMode
    dedupe_key: str


@dataclass
class SarifImport:
    items: list[ImportedFinding] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    read: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    truncated: int = 0

    @property
    def findings(self) -> list[FailureMode]:
        return [i.failure for i in self.items]


def _d(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _l(x: Any) -> list:
    return x if isinstance(x, list) else []


def _text(value: Any, limit: int = 600) -> str:
    if isinstance(value, dict):
        value = value.get("text") or value.get("markdown") or ""
    if isinstance(value, (dict, list)):
        return ""
    return re.sub(r"\s+", " ", sanitize_text(str(value or ""), limit * 2)).strip()[:limit]


def _clean_path(uri: Any) -> str:
    """A relative path, or '' when the URI is absolute, climbs out of the project, or is not a file path."""
    text = str(uri or "").strip().replace("\\", "/")
    if text.lower().startswith("file://"):
        text = text[7:]
    if not text or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", text) or text.startswith("/") or ".." in text.split("/"):
        return ""
    while text.startswith("./"):
        text = text[2:]
    return text[:300]


def _find_file(path: str, files: dict[str, str]) -> str | None:
    """The stored file for a path: an exact match, or the only stored file the path is a suffix of (or the reverse)."""
    if path in files:
        return path
    matches = [p for p in files if p.endswith("/" + path) or path.endswith("/" + p)]
    return matches[0] if len(matches) == 1 else None


def _location(result: dict) -> tuple[str, int | None, int | None, str]:
    locs = _l(result.get("locations"))
    phys = _d(_d(locs[0]).get("physicalLocation")) if locs else {}
    region = _d(phys.get("region"))
    start = region.get("startLine") if isinstance(region.get("startLine"), int) and region["startLine"] > 0 else None
    end = region.get("endLine") if isinstance(region.get("endLine"), int) and region["endLine"] >= (start or 1) else start
    return _clean_path(_d(phys.get("artifactLocation")).get("uri")), start, end, _text(_d(region.get("snippet")).get("text"), 500)


def _flow_steps(result: dict) -> list[str]:
    for flow in _l(result.get("codeFlows"))[:3]:
        steps: list[str] = []
        for tf in _l(_d(flow).get("threadFlows"))[:3]:
            for item in _l(_d(tf).get("locations"))[:40]:
                loc = _d(_d(item).get("location"))
                path, start, _, _ = _location({"locations": [loc]})
                step = " ".join(x for x in (f"{path}:{start}" if path and start else path, _text(loc.get("message"), 200)) if x)
                if step:
                    steps.append(step)
            if steps:
                return steps[:12]
    return []


def _rule_cwe(rule: dict) -> str:
    """CWE of a rule: its tags and properties, else its relationships to a CWE taxonomy. Computed once per rule."""
    props = _d(rule.get("properties"))
    values: list[Any] = [str(t)[:200] for t in _l(props.get("tags"))[:MAX_TAGS]] + [str(props.get("cwe") or "")[:200]]
    found = first_cwe(values)
    if found != UNMAPPED:
        return found
    for rel in _l(rule.get("relationships"))[:50]:
        target = _d(_d(rel).get("target"))
        if str(_d(target.get("toolComponent")).get("name") or "").upper() == "CWE" and str(target.get("id") or "").strip().isdigit():
            return normalise_cwe(f"CWE-{str(target['id']).strip()[:6]}")
    return UNMAPPED


def parse_sarif(data: Any, files: dict[str, str] | None = None) -> SarifImport:
    """Read a SARIF 2.1.0 log (dict, str or bytes). Raises SarifError when it is not usable."""
    try:
        return _parse(data, files or {})
    except RecursionError:
        raise SarifError("The file is nested too deeply.") from None


def _parse(data: Any, files: dict[str, str]) -> SarifImport:
    if isinstance(data, (bytes, str)):
        if len(data) > MAX_BYTES:
            raise SarifError("The file is larger than 10 MB.")
        try:
            data = json.loads(data)
        except ValueError:
            raise SarifError("The file is not valid JSON.") from None
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        raise SarifError("This is not a SARIF log: it has no 'runs'.")
    if str(data.get("version", "")) != "2.1.0":
        raise SarifError(f"Only SARIF version 2.1.0 is supported (this file says {_text(data.get('version'), 20)!r}).")

    out = SarifImport()
    lines_of: dict[str, list[str]] = {}
    for run in data["runs"]:
        run = _d(run)
        driver = _d(_d(run.get("tool")).get("driver"))
        tool = _text(driver.get("name"), 80) or "unknown tool"
        if tool not in out.tools:
            out.tools.append(tool)
        rules = [_d(r) for r in _l(driver.get("rules"))]
        by_id = {r.get("id"): r for r in rules if isinstance(r.get("id"), str)}
        cwe_of: dict[int, str] = {}
        for result in _l(run.get("results")):
            if not isinstance(result, dict):
                continue
            out.read += 1
            if len(out.items) >= MAX_RESULTS:
                out.truncated += 1
                continue
            rule_id = _text(result.get("ruleId") or _d(result.get("rule")).get("id"), 120)
            index = result.get("ruleIndex")
            rule = (by_id.get(result.get("ruleId")) if isinstance(result.get("ruleId"), str) else None) or (rules[index] if isinstance(index, int) and 0 <= index < len(rules) else {})
            raw_message = _text(result.get("message"), 2000)
            message = raw_message[:600]
            if not rule_id and not message:
                out.skipped["no rule and no message"] = out.skipped.get("no rule and no message", 0) + 1
                continue
            path, start, end, snippet = _location(result)
            title = _text(rule.get("shortDescription") or rule.get("name"), 120) or rule_id or message[:120]
            name = f"{title} ({path}:{start})" if path and start else f"{title} ({path})" if path else title
            quote_text = snippet
            stored = _find_file(path, files) if path else None
            if stored and start:
                lines = lines_of.setdefault(stored, files[stored].splitlines())
                picked = lines[start - 1:min(end or start, start + 4)]
                if picked:
                    quote_text = "\n".join(l.rstrip() for l in picked)[:500]
            evidence = None
            if path and start:
                evidence = f"{path}:{start}" + (f"-{end}" if end and end != start else "") + (f" `{quote_text}`" if quote_text else "")
            props = _d(rule.get("properties"))
            level = _text(result.get("level") or _d(rule.get("defaultConfiguration")).get("level") or "warning", 20)
            severity = _text(props.get("security-severity"), 20)
            trigger = f"Reported by {tool}, rule {rule_id or 'unknown'}, level {level}" + (f", security-severity {severity}" if severity else "")
            if id(rule) not in cwe_of:
                cwe_of[id(rule)] = _rule_cwe(rule)
            cwe = cwe_of[id(rule)]
            if cwe == UNMAPPED:
                cwe = first_cwe(str(t)[:200] for t in _l(_d(result.get("properties")).get("tags"))[:MAX_TAGS])
            failure = FailureMode(
                failure_mode=name[:160],
                attack_chain=_flow_steps(result) or ([message] if message else [title]),
                business_impact=_text(rule.get("fullDescription"), 400) or message or "Not specified",
                blast_radius="Not specified",
                trigger=trigger[:300],
                evidence=evidence,
                source=f"import:{tool}",
                cwe=cwe,
            )
            key = hashlib.sha256(f"{tool}|{rule_id}|{path}|{start}|{raw_message}".encode("utf-8")).hexdigest()[:24]
            out.items.append(ImportedFinding(failure, key))
    return out


# ── merging with our findings ─────────────────────────────────────────────────

_LOC = re.compile(r"([\w./\\-]+\.\w{1,8}):(\d+)(?:\s*-\s*(\d+))?")


def _where(evidence: str | None) -> tuple[str, int, int] | None:
    m = _LOC.search(evidence or "")
    if not m:
        return None
    start = int(m.group(2))
    if start < 1:
        return None
    path = m.group(1).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path, start, max(int(m.group(3) or start), start)


def _same_file(a: str, b: str) -> bool:
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _distance(a: str | None, b: str | None) -> int | None:
    """Lines between two evidence locations in the same file, or None when they are elsewhere."""
    wa, wb = _where(a), _where(b)
    if not wa or not wb or not _same_file(wa[0], wb[0]):
        return None
    gap = max(wa[1] - wb[2], wb[1] - wa[2], 0)
    return gap if gap <= LINE_SLACK else None


def _unique_name(name: str, taken: set[str], tool: str) -> str:
    if name not in taken:
        return name
    base = f"{name} [{tool}]"[:165]
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base} #{n}", n + 1
    return candidate


def merge_imported(failures: list[FailureMode], imported: list[FailureMode]) -> tuple[list[FailureMode], int, int]:
    """Our findings plus the imported ones. A finding with the same code quote merges into the earlier one (its text
    and scores win; the other tool is recorded). Returns (findings, added, merged); added findings come last, so
    existing positions do not move. Location matches are made later, by `merge_by_place`, once our CWE is known."""
    merged_list = list(failures)
    added = merged = 0
    for imp in imported:
        ident = finding_identity(imp.evidence)
        target = next((k for k, ours in enumerate(merged_list) if ident and finding_identity(ours.evidence) == ident), None)
        if target is None:
            tool = imp.source.removeprefix("import:")
            merged_list.append(imp.model_copy(update={"failure_mode": _unique_name(imp.failure_mode, {f.failure_mode for f in merged_list}, tool)}))
            added += 1
            continue
        ours = merged_list[target]
        tool = imp.source.removeprefix("import:")
        update: dict = {}
        if tool != ours.source.removeprefix("import:") and tool not in ours.also_reported_by:
            update["also_reported_by"] = [*ours.also_reported_by, tool]
        if ours.cwe == UNMAPPED and imp.cwe != UNMAPPED:
            update["cwe"] = imp.cwe
        merged_list[target] = ours.model_copy(update=update) if update else ours
        merged += 1
    return merged_list, added, merged


def merge_by_place(failures: list[FailureMode]) -> tuple[list[FailureMode], list[int], int]:
    """Drop an imported finding that reports our own finding again: same CWE (both known), same file, lines within
    three. The nearest of our findings gets the other tool's name. Returns (findings, kept positions, dropped)."""
    out = list(failures)
    drop: set[int] = set()
    for k, imp in enumerate(failures):
        if imp.source == "fmea" or imp.cwe == UNMAPPED:
            continue
        best = None
        for j, ours in enumerate(out):
            if ours.source != "fmea" or ours.cwe != imp.cwe:
                continue
            gap = _distance(ours.evidence, imp.evidence)
            if gap is not None and (best is None or gap < best[0]):
                best = (gap, j)
        if best is None:
            continue
        j, tool = best[1], imp.source.removeprefix("import:")
        if tool not in out[j].also_reported_by:
            out[j] = out[j].model_copy(update={"also_reported_by": [*out[j].also_reported_by, tool]})
        drop.add(k)
    kept = [k for k in range(len(failures)) if k not in drop]
    return [out[k] for k in kept], kept, len(drop)


# ── export ────────────────────────────────────────────────────────────────────

_LEVEL = {"Critical": "error", "High": "error", "Medium": "warning", "Low": "note"}


def export_sarif(result: dict, states: dict[str, str] | None = None) -> dict:
    """Our results (a stored scan, as plain dicts) as a SARIF 2.1.0 log."""
    states = states or {}
    risks = {r.get("failure_mode"): r for r in result.get("risks") or []}
    causes = {r.get("failure_mode"): r for r in result.get("root_causes") or []}
    rules: dict[str, dict] = {}
    results = []
    for f in result.get("failures") or []:
        name = f.get("failure_mode", "")
        risk, cause = risks.get(name, {}), causes.get(name, {})
        cwe = f.get("cwe") or UNMAPPED
        ident = finding_identity(f.get("evidence"))
        rule_id = cwe if cwe != UNMAPPED else "FMEA-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]
        if rule_id not in rules:
            rule = {"id": rule_id, "name": rule_id, "shortDescription": {"text": cwe if cwe != UNMAPPED else name[:200]}}
            if cwe != UNMAPPED:
                rule["helpUri"] = f"https://cwe.mitre.org/data/definitions/{cwe.split('-')[1]}.html"
            rules[rule_id] = rule
        item: dict = {
            "ruleId": rule_id,
            "level": _LEVEL.get(risk.get("priority"), "warning"),
            "message": {"text": f"{name}: {f.get('business_impact', '')}"[:1000]},
            "properties": {
                "findingName": name, "source": f.get("source", "fmea"), "cwe": cwe,
                "alsoReportedBy": list(f.get("also_reported_by") or []),
                "rpn": risk.get("rpn"), "severity": risk.get("severity"), "occurrence": risk.get("occurrence"),
                "detection": risk.get("detection"), "priority": risk.get("priority"),
                "rootCause": cause.get("primary"), "state": states.get(name),
            },
        }
        if ident:
            item["partialFingerprints"] = {"findingIdentity/v1": ident}
        where = _where(f.get("evidence"))
        if where:
            item["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": quote(where[0], safe="/")},
                                                       "region": {"startLine": where[1], "endLine": where[2]}}}]
        results.append(item)
    return {
        "$schema": SARIF_SCHEMA, "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "FMEA Automation", "rules": list(rules.values())}}, "results": results}],
    }
