"""
Spike adapter for the in-house index: core/code_index.py (promoted from the original prototype, ADR-025)
reading a repository directory and returning the common shape used by score_index.
"""

from __future__ import annotations

from pathlib import Path

from core.code_index import build_index


def index_repo(repo: Path) -> dict:
    repo = Path(repo)
    files = {p.relative_to(repo).as_posix(): p.read_text(encoding="utf-8", errors="replace")
             for p in sorted(repo.rglob("*")) if p.is_file() and p.suffix.lower() not in (".json", ".md")}
    index = build_index(files)
    return {
        "symbols": [{"file": s.file, "name": s.name, "line": s.line} for s in index.symbols if s.kind != "class"],
        "calls": [{"caller_file": c.caller_file, "caller": c.caller, "callee": c.callee, "callee_file": c.callee_file or None}
                  for c in index.edges()],
        "entry_points": [{"file": e.file, "kind": e.kind, "symbol": e.symbol, "route": e.route} for e in index.entry_points],
        "sinks": [{"file": s.file, "kind": s.kind, "line": s.line} for s in index.sinks],
    }
