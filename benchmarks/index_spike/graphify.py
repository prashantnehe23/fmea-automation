"""
Adapter for Graphify (graphifyy, offline `graphify update`, code only) output: reads graphify-out/graph.json.

The graph must be produced beforehand in $SPIKE_GRAPHIFY_DIR/<repo>/graphify-out (see the ADR-025 notes for the
exact, network-blocked command). Graphify provides symbols and call edges, no entry-point or sink detection.
Set SPIKE_GRAPHIFY_EXTRACTED_ONLY=1 to drop edges it tags INFERRED.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _name(label: str) -> str:
    return label.strip().rstrip("()").split(".")[-1].rstrip("()")


def index_repo(repo: Path) -> dict:
    graph = json.loads((Path(os.environ["SPIKE_GRAPHIFY_DIR"]) / Path(repo).name / "graphify-out" / "graph.json")
                       .read_text(encoding="utf-8"))
    extracted_only = os.environ.get("SPIKE_GRAPHIFY_EXTRACTED_ONLY") == "1"
    nodes = {n["id"]: n for n in graph["nodes"]}
    functions = {i: n for i, n in nodes.items() if n["label"].endswith("()")}
    symbols = [{"file": n["source_file"], "name": _name(n["label"]),
                "line": int(str(n.get("source_location", "L1")).lstrip("L").split("-")[0] or 1)} for n in functions.values()]
    calls = []
    for e in graph["links"]:
        if e.get("relation") != "calls" or e["source"] not in functions or e["target"] not in functions:
            continue
        if extracted_only and e.get("confidence") != "EXTRACTED":
            continue
        s, t = functions[e["source"]], functions[e["target"]]
        calls.append({"caller_file": s["source_file"], "caller": _name(s["label"]),
                      "callee": _name(t["label"]), "callee_file": t["source_file"]})
    return {"symbols": symbols, "calls": calls, "entry_points": None, "sinks": None}
