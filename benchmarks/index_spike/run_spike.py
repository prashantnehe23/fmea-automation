"""
Run the code-index candidates over the spike repositories and print a comparison table (B-036).

    <python with tree-sitter wheels> -m benchmarks.index_spike.run_spike [inhouse|graphify|codegraph ...]
"""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

from benchmarks.index_spike.score_index import load_truth, score

ROOT = Path(__file__).resolve().parents[1] / "index_repos"
COLUMNS = ("call_recall", "call_precision", "symbol_recall", "entry_recall", "entry_precision", "sink_recall", "sink_precision")


def run(candidate: str) -> dict:
    adapter = importlib.import_module(f"benchmarks.index_spike.{candidate}")
    results = {}
    for repo in sorted(p for p in ROOT.iterdir() if (p / "index_truth.json").exists()):
        started = time.perf_counter()
        try:
            pred = adapter.index_repo(repo)
            s = score(load_truth(repo), pred)
            s["seconds"] = round(time.perf_counter() - started, 2)
        except Exception as exc:                     # a candidate that cannot index a language is a result
            s = {"error": f"{type(exc).__name__}: {exc}"}
        results[repo.name] = s
    return results


def fmt(v) -> str:
    return "  -  " if v is None else f"{v:.2f}"


def table(name: str, results: dict) -> str:
    lines = [f"== {name}", f"{'repo':<14}" + "".join(f"{c.replace('_', ' '):>15}" for c in COLUMNS) + f"{'sec':>7}"]
    for repo, s in results.items():
        if "error" in s:
            lines.append(f"{repo:<14}ERROR {s['error'][:90]}")
        else:
            lines.append(f"{repo:<14}" + "".join(f"{fmt(s.get(c)):>15}" for c in COLUMNS) + f"{s['seconds']:>7}")
    return "\n".join(lines)


if __name__ == "__main__":
    names = sys.argv[1:] or ["inhouse"]
    for n in names:
        res = run(n)
        print(table(n, res))
        out = Path(__file__).resolve().parent / f"result_{n}.json"
        out.write_text(json.dumps(res, indent=2), encoding="utf-8")
