"""
Score a code index against index_truth.json (B-036 spike).

Every candidate is adapted to one output shape:

    {"symbols":      [{"file", "name", "line"}],
     "calls":        [{"caller_file", "caller", "callee", "callee_file"?}],     # callee_file when the tool resolves it
     "entry_points": [{"file", "kind", "symbol"}]  | None,                       # None = the tool does not provide it
     "sinks":        [{"file", "kind", "line"}]    | None}

Callers are scored by name (a call edge found iff a call from the labelled caller to the labelled callee
name exists, and its callee_file, if given, is the labelled file); entry points by (file, kind, symbol for
http); sinks by (file, kind, line within +/- 1).
"""

from __future__ import annotations

import json
from pathlib import Path

LINE_TOLERANCE = 1


def load_truth(repo_dir: Path) -> dict:
    return json.loads((Path(repo_dir) / "index_truth.json").read_text(encoding="utf-8"))


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _edge_found(edge: dict, calls: list[dict]) -> bool:
    callee, caller = edge["callee"], edge["caller"]
    for c in calls:
        if (c["caller_file"] == caller["file"] and c["caller"] == caller["symbol"]
                and c["callee"] == callee["symbol"] and c.get("callee_file") in (None, callee["file"])):
            return True
    return False


def score_calls(truth: dict, pred: dict) -> dict:
    calls = pred.get("calls") or []
    found = sum(_edge_found(e, calls) for e in truth["calls"])
    labelled_callees = {(e["callee"]["symbol"]) for e in truth["calls"]}
    # precision: predicted edges into a labelled callee that the truth does not contain
    relevant = [c for c in calls if c["callee"] in labelled_callees]
    true_pairs = {(e["caller"]["file"], e["caller"]["symbol"], e["callee"]["symbol"]) for e in truth["calls"]}
    correct = sum((c["caller_file"], c["caller"], c["callee"]) in true_pairs for c in relevant)
    names = {(s["file"], s["name"]) for s in pred.get("symbols") or []}
    wanted = {(e[k]["file"], e[k]["symbol"]) for e in truth["calls"] for k in ("callee", "caller")}
    return {"call_recall": _ratio(found, len(truth["calls"])), "call_precision": _ratio(correct, len(relevant)),
            "symbol_recall": _ratio(len(wanted & names), len(wanted)), "calls_found": found, "calls_total": len(truth["calls"])}


def score_entry_points(truth: dict, pred: dict) -> dict:
    if pred.get("entry_points") is None:
        return {"entry_recall": None, "entry_precision": None}

    def key(e):
        return (e["file"], e["kind"], e["symbol"] if e["kind"] == "http" else None)

    want = {key(e) for e in truth["entry_points"]}
    got = {key(e) for e in pred["entry_points"]}
    return {"entry_recall": _ratio(len(want & got), len(want)), "entry_precision": _ratio(len(want & got), len(got))}


def score_sinks(truth: dict, pred: dict) -> dict:
    if pred.get("sinks") is None:
        return {"sink_recall": None, "sink_precision": None}
    want, got = truth["sinks"], pred["sinks"]

    def hit(s, others):
        return any(o["file"] == s["file"] and o["kind"] == s["kind"] and abs(o["line"] - s["line"]) <= LINE_TOLERANCE
                   for o in others)

    return {"sink_recall": _ratio(sum(hit(s, got) for s in want), len(want)),
            "sink_precision": _ratio(sum(hit(s, want) for s in got), len(got))}


def score(truth: dict, pred: dict) -> dict:
    return {**score_calls(truth, pred), **score_entry_points(truth, pred), **score_sinks(truth, pred)}
