"""
benchmarks/report.py — B-026 phase 3: score stored benchmark runs and print a comparison table.

    python -m benchmarks.report benchmarks/results/baseline-*.json

Scoring happens here, offline, from the stored findings, so labels can be corrected and the
same raw runs re-scored without paying for a new scan.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from benchmarks.score import load_repo_files, load_truth, score_scan, stability

REPOS_DIR = Path(__file__).resolve().parent / "repos"


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


_BLOCK_MARKERS = ("provider_blocked", "guardrail", "1920", "content_filter")


def is_blocked_run(run: dict) -> bool:
    """A run the provider refused. Runs stored before B-040 carry no flag, only the provider's error text."""
    return bool(run.get("blocked")) or any(m in str(run.get("error") or "").lower() for m in _BLOCK_MARKERS)


def summarise(result: dict, repos_dir: Path = REPOS_DIR) -> dict:
    """Per-repository and overall metrics for one stored result file (failed scans are excluded)."""
    totals: dict[str, int] = {}
    per_repo: dict[str, dict] = {}
    stabilities = []
    for name, data in result["repos"].items():
        truth, files = load_truth(repos_dir / name), load_repo_files(repos_dir / name)
        ok = [r for r in data["runs"] if not r["error"]]
        scores = [score_scan(r["findings"], truth, files) for r in ok]
        agg = {k: sum(s["counts"][k] for s in scores) for k in
               ("truth", "findings", "matched", "matched_findings", "catastrophic", "caught_catastrophic",
                "placed", "with_path", "traced", "valid_evidence", "line_on_target")}
        for k, v in agg.items():
            totals[k] = totals.get(k, 0) + v
        stab = stability(scores) if len(scores) > 1 else None
        if stab is not None:
            stabilities.append(stab)
        per_repo[name] = {
            "runs_ok": len(ok), "runs_failed": len(data["runs"]) - len(ok),
            "runs_blocked": sum(1 for r in data["runs"] if is_blocked_run(r)), "runs_total": len(data["runs"]),
            **_metrics(agg), "stability": stab,
            "missed": sorted({m for s in scores for m in s["missed"]}),
            "missed_catastrophic": sorted({m for s in scores for m in s["missed_catastrophic"]}),
            "cost_usd": round(sum(r["cost_usd"] for r in data["runs"]), 4),
            "seconds": round(sum(r["seconds"] for r in data["runs"]), 1),
            "llm_calls": sum(r["llm_calls"] for r in data["runs"]),
        }
    overall = {**_metrics(totals),
               "stability": round(sum(stabilities) / len(stabilities), 3) if stabilities else None,
               "cost_usd": round(sum(r["cost_usd"] for r in per_repo.values()), 4),
               "seconds": round(sum(r["seconds"] for r in per_repo.values()), 1),
               "llm_calls": sum(r["llm_calls"] for r in per_repo.values()),
               "runs_failed": sum(r["runs_failed"] for r in per_repo.values()),
               "runs_blocked": sum(r["runs_blocked"] for r in per_repo.values()),
               "runs_total": sum(r["runs_total"] for r in per_repo.values())}
    overall["block_rate"] = round(overall["runs_blocked"] / overall["runs_total"], 3) if overall["runs_total"] else None
    return {"meta": result["meta"], "repos": per_repo, "overall": overall}


def _metrics(c: dict) -> dict:
    return {
        "recall": _ratio(c["matched"], c["truth"]),
        "precision": _ratio(c["matched_findings"], c["findings"]),
        "catastrophic_recall": _ratio(c["caught_catastrophic"], c["catastrophic"]),
        "placement": _ratio(c["placed"], c["caught_catastrophic"]),
        "path_accuracy": _ratio(c["traced"], c["with_path"]),
        "evidence_validity": _ratio(c["valid_evidence"], c["findings"]),
        "line_accuracy": _ratio(c["line_on_target"], c["matched"]),
    }


COLUMNS = (("recall", "recall"), ("precision", "prec"), ("catastrophic_recall", "cat.rec"), ("placement", "place"),
           ("path_accuracy", "path"), ("evidence_validity", "evid"), ("line_accuracy", "line"), ("stability", "stab"))


def _cell(v) -> str:
    return "  -  " if v is None else f"{v:.2f}"


def format_table(summaries: list[dict]) -> str:
    lines = []
    for s in summaries:
        m = s["meta"]
        head = f"{m['label']} · {m['model']} · reasoning {m['reasoning']} · {m['runs']} runs · {m['created']}"
        if not all(m["signed_off"].values()):
            head += "  [labels were not signed off when this ran]"
        if m.get("stopped"):
            head += f"  [STOPPED: {m['stopped']}]"
        lines += [head, f"{'repository':<18}" + "".join(f"{h:>9}" for _, h in COLUMNS) + f"{'$':>9}{'sec':>8}"]
        for name, r in {**s["repos"], "OVERALL": s["overall"]}.items():
            lines.append(f"{name:<18}" + "".join(f"{_cell(r.get(k)):>9}" for k, _ in COLUMNS)
                         + f"{r['cost_usd']:>9.3f}{r['seconds']:>8.0f}")
        misses = {n: r["missed_catastrophic"] for n, r in s["repos"].items() if r["missed_catastrophic"]}
        if misses:
            lines.append("missed catastrophic: " + "; ".join(f"{n}: {', '.join(v)}" for n, v in misses.items()))
        o = s["overall"]
        lines.append(f"blocked: {o['runs_blocked']} of {o['runs_total']} scans by the provider's policy"
                     + (f" ({o['block_rate']:.0%})" if o["block_rate"] is not None else ""))
        if o["runs_failed"]:
            lines.append(f"failed scans (excluded, blocked ones included): {o['runs_failed']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        paths = sorted((Path(__file__).resolve().parent / "results").glob("*.json"))
    if not paths:
        sys.exit("No result files. Run `make bench` first.")
    print(format_table([summarise(json.loads(p.read_text(encoding="utf-8"))) for p in paths]))


if __name__ == "__main__":
    main()
