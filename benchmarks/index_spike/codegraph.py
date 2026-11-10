"""
Adapter for CodeGraph (@colbymchenry/codegraph): reads the SQLite index its `codegraph init` wrote to
$SPIKE_CODEGRAPH_DIR/<repo>/.codegraph/codegraph.db. Provides symbols, call edges with resolved callee files and,
for some frameworks, route nodes (entry points); no main-entry or sink detection.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_FUNCS = ("function", "method")


def index_repo(repo: Path) -> dict:
    db = Path(os.environ["SPIKE_CODEGRAPH_DIR"]) / Path(repo).name / ".codegraph" / "codegraph.db"
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    nodes = {r[0]: r[1:] for r in con.execute("select id, kind, name, file_path, start_line from nodes")}
    symbols = [{"file": fp, "name": name, "line": line} for _, (kind, name, fp, line) in nodes.items() if kind in _FUNCS]
    calls = []
    for s, t in con.execute("select source, target from edges where kind = 'calls'"):
        a, b = nodes.get(s), nodes.get(t)
        if a and b and a[0] in _FUNCS and b[0] in _FUNCS:
            calls.append({"caller_file": a[2], "caller": a[1], "callee": b[1], "callee_file": b[2]})
    entries = []
    for s, t in con.execute("select source, target from edges where kind = 'references'"):
        a, b = nodes.get(s), nodes.get(t)
        if a and b and a[0] == "route" and b[0] in _FUNCS:
            entries.append({"file": b[2], "kind": "http", "symbol": b[1]})
    con.close()
    return {"symbols": symbols, "calls": calls, "entry_points": entries, "sinks": None}
