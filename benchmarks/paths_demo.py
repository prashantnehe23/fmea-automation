"""
benchmarks/paths_demo.py — B-028 phase B: run the exploit-path workflow on a directory and store what it found.

    python -m benchmarks.paths_demo --dir benchmarks/repos/chain-api --model mistral-large-4 --reasoning low --label demo

The scan runs in an isolated environment (temporary database, cache and settings), as the benchmark does. The result holds
each finding with its exploit path and verification, the discovery counts, the files that were not hunted, cost and time.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

from benchmarks.run import findings_from_result, isolated_environment, read_api_keys
from benchmarks.score import load_repo_files

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def run_paths(directory: Path, model: str, reasoning: str, keys: dict, max_batches: int = 5, run_fmea=None) -> dict:
    from core.llm import get_call_count
    from core.provider_block import ProviderBlocked
    from core.scan_scope import build_scan_input
    from core.untrusted import sanitize_text
    from core.workspace import WorkspaceContext

    if run_fmea is None:
        from workflows.fmea_pipeline import run_fmea
    scan = build_scan_input(load_repo_files(directory), max_batches=max_batches)
    batches = scan.batch_codes if len(scan.batch_codes) > 1 else None
    started = time.perf_counter()
    out = {"findings": [], "error": None, "blocked": False}
    with tempfile.TemporaryDirectory(prefix="fmea-paths-") as tmp:
        with isolated_environment(Path(tmp), model, reasoning, keys):
            import memory.db as db
            ws = WorkspaceContext(customer="demo", project=directory.name, function="", business_tier="Tier 1",
                                  user_type="external_customers", business_context=sanitize_text(scan.readme_text, 2000),
                                  customer_learning=True)
            try:
                def progress(stage):
                    print(f"[{time.perf_counter() - started:6.0f}s] stage {stage}", flush=True)
                result = run_fmea(scan.code, force_rerun=True, workspace=ws, max_failure_modes=None, discovery="paths",
                                  on_progress=progress, **({"batches": batches} if batches else {}))
                findings = findings_from_result(result)
                for f, source in zip(findings, result["failures"]):
                    f["exploit_path"] = [s.model_dump() for s in source.exploit_path]
                    f["path_status"] = source.path_status
                out.update(findings=findings, discovery=result.get("discovery"), model_replies_cut=result.get("model_replies_cut"))
            except ProviderBlocked as exc:
                out.update(error=f"provider_blocked: {exc}", blocked=True)
            except Exception as exc:
                out["error"] = f"{type(exc).__name__}: {exc}"
            conn = db.get_db()
            try:
                cost = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM telemetry").fetchone()[0]
            finally:
                conn.close()
    out.update(cost_usd=round(float(cost), 4), seconds=round(time.perf_counter() - started, 1), llm_calls=get_call_count(), model=model)
    return out


def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--reasoning", default="off")
    ap.add_argument("--label", default="paths")
    ap.add_argument("--max-batches", type=int, default=5)
    args = ap.parse_args(argv)
    directory = Path(args.dir)
    result = run_paths(directory, args.model, args.reasoning, read_api_keys(), args.max_batches)
    result["created"] = datetime.now().isoformat(timespec="seconds")
    result["project"] = directory.name
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"paths-{args.label}-{directory.name}-{args.model}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{directory.name}: {len(result['findings'])} findings, discovery {result.get('discovery')}, ${result['cost_usd']}, {result['seconds']}s"
          + (f"  ERROR {result['error']}" if result["error"] else ""))
    print(f"Wrote {path}")
    return path


if __name__ == "__main__":
    main()
