"""
benchmarks/run.py — B-026 phase 3: scan the benchmark repositories and store the raw findings.

    python -m benchmarks.run --model mistral-large-4 --reasoning off --runs 3 --label baseline

Each scan runs against a temporary database, cache, learning memory and settings file, so a
benchmark never touches the real fmea.db, memory files or settings.json (API keys are read
from the real settings and copied into the temporary ones). Every run gets a fresh
environment, otherwise the scenario registry would lock run 1's scores and make runs 2..N
meaningless. Scoring is separate (benchmarks/report.py) and re-runs offline on stored findings.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from unittest import mock

from benchmarks.score import load_repo_files, load_truth

ROOT = Path(__file__).resolve().parents[1]
REPOS_DIR = Path(__file__).resolve().parent / "repos"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_MAX_USD = 12.0


# ── What a scan sees ──────────────────────────────────────────────────────────

def scan_input(repo_dir: Path) -> tuple[str, str]:
    """(code, business_context) exactly as the GitHub scan flow would build them for this tree."""
    from core.scan_scope import build_scan_input
    from core.untrusted import sanitize_text

    files = load_repo_files(repo_dir)                       # truth.json is never shown to a scan
    scan = build_scan_input(files)
    return scan.code, sanitize_text(scan.readme_text, 2000)


# ── Isolation ─────────────────────────────────────────────────────────────────

def read_api_keys() -> dict[str, str]:
    """Keys from the real settings or environment, read before anything is redirected."""
    from core import providers
    return {p: k for p in providers.PROVIDERS if (k := providers.get_api_key(p))}


@contextmanager
def isolated_environment(tmp: Path, model: str, reasoning: str, api_keys: dict[str, str]):
    """Redirect every store the pipeline writes to into `tmp` and configure the model there."""
    import core.settings as settings
    import core.workspace as core_workspace
    import memory.analysis_cache as analysis_cache
    import memory.db as db
    import memory.eval_store as eval_store
    import memory.learning_memory as learning_memory
    import memory.workspace_store as workspace_store
    from core import llm, providers

    memory_dir = tmp / "memory"
    with ExitStack() as stack:
        for target, name, value in (
            (db, "_DB_PATH", tmp / "fmea.db"),
            (settings, "_SETTINGS_PATH", tmp / "settings.json"),
            (core_workspace, "_MEMORY_ROOT", memory_dir),
            (workspace_store, "_MEMORY_ROOT", memory_dir),
            (workspace_store, "_CORE_DIR", memory_dir / "core"),
            (eval_store, "_MEMORY_ROOT", memory_dir),
            (eval_store, "_CORE_DIR", memory_dir / "core"),
            (analysis_cache, "CACHE_PATH", memory_dir / "analysis_cache.json"),
            (learning_memory, "LEARNING_PATH", memory_dir / "learning_memory.json"),
        ):
            stack.enter_context(mock.patch.object(target, name, value))
        settings.set_setting("active_model", model)
        settings.set_setting("reasoning_level", reasoning)
        for provider, key in api_keys.items():
            providers.set_api_key(provider, key)
        llm._clients.clear()
        try:
            yield
        finally:
            llm._clients.clear()


# ── One scan ──────────────────────────────────────────────────────────────────

def findings_from_result(result: dict) -> list[dict]:
    """The scan's findings as plain dicts: what the scorer and the stored results use."""
    validations = result.get("validations") or []
    out = []
    for i, (f, r) in enumerate(zip(result["failures"], result["risks"])):
        out.append({
            "failure_mode": f.failure_mode, "trigger": f.trigger, "evidence": f.evidence,
            "business_impact": f.business_impact, "blast_radius": f.blast_radius,
            "attack_chain": list(f.attack_chain),
            "severity": r.severity, "occurrence": r.occurrence, "detection": r.detection,
            "rpn": r.rpn, "priority": r.priority,
            "validator_confidence": validations[i].confidence if i < len(validations) else None,
        })
    return out


def run_once(repo_dir: Path, model: str, reasoning: str, run_index: int, api_keys: dict[str, str],
             run_fmea=None) -> dict:
    """Scan one repository in a fresh isolated environment. Never raises: errors are recorded."""
    if run_fmea is None:
        from workflows.fmea_pipeline import run_fmea
    from core.llm import get_call_count
    from core.workspace import WorkspaceContext

    code, context = scan_input(repo_dir)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="fmea-bench-") as tmp:
        with isolated_environment(Path(tmp), model, reasoning, api_keys):
            import memory.db as db
            ws = WorkspaceContext(customer="benchmark", project=f"{repo_dir.name}-{run_index}", function="",
                                  business_tier="Tier 1", user_type="external_customers",
                                  business_context=context, customer_learning=True)
            try:
                result = run_fmea(code, force_rerun=True, workspace=ws)
                findings, error = findings_from_result(result), None
            except Exception as exc:        # a failed scan is data, not a reason to stop the benchmark
                findings, error = [], f"{type(exc).__name__}: {exc}"
            conn = db.get_db()
            try:
                cost = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM telemetry").fetchone()[0]
            finally:
                conn.close()
            calls = get_call_count()
    return {"findings": findings, "error": error, "cost_usd": round(float(cost), 6),
            "seconds": round(time.perf_counter() - started, 1), "llm_calls": calls}


# ── Whole benchmark ───────────────────────────────────────────────────────────

def _git_state() -> dict:
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--", ":!memory/fmea.db"))}


def run_benchmark(model: str, reasoning: str, runs: int, repos: list[Path], label: str,
                  max_usd: float, allow_unsigned: bool, api_keys: dict[str, str], run_fmea=None) -> dict:
    truths = {r.name: load_truth(r, require_signed_off=not allow_unsigned) for r in repos}
    result = {"meta": {"label": label, "model": model, "reasoning": reasoning, "runs": runs,
                       "created": datetime.now().isoformat(timespec="seconds"), "git": _git_state(),
                       "signed_off": {n: t.get("signed_off_by") for n, t in truths.items()},
                       "max_usd": max_usd, "stopped": None},
              "repos": {}}
    total = 0.0
    for repo in repos:
        result["repos"][repo.name] = {"runs": []}
        for i in range(1, runs + 1):
            if total >= max_usd:
                result["meta"]["stopped"] = f"budget ${max_usd:.2f} reached before {repo.name} run {i}"
                result["meta"]["total_cost_usd"] = round(total, 4)
                return result
            one = run_once(repo, model, reasoning, i, api_keys, run_fmea)
            total += one["cost_usd"]
            result["repos"][repo.name]["runs"].append(one)
            print(f"{repo.name} run {i}/{runs}: {len(one['findings'])} findings, ${one['cost_usd']:.3f}, "
                  f"{one['seconds']}s" + (f"  ERROR {one['error']}" if one["error"] else ""), flush=True)
    result["meta"]["total_cost_usd"] = round(total, 4)
    return result


def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser(description="Scan the benchmark repositories and store the raw findings.")
    ap.add_argument("--model", help="model id (default: the active model in settings)")
    ap.add_argument("--reasoning", default="off", help="off | low | medium | high (default off)")
    ap.add_argument("--runs", type=int, default=3, help="scans per repository (default 3)")
    ap.add_argument("--repo", action="append", help="repository name; repeat for several (default all)")
    ap.add_argument("--label", default="run")
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="stop launching scans past this spend")
    ap.add_argument("--allow-unsigned", action="store_true", help="run repositories whose labels are not signed off")
    args = ap.parse_args(argv)

    from core import settings
    model = args.model or settings.get_setting("active_model")
    names = args.repo or sorted(p.parent.name for p in REPOS_DIR.glob("*/truth.json"))
    repos = [REPOS_DIR / n for n in names]
    keys = read_api_keys()
    result = run_benchmark(model, args.reasoning, args.runs, repos, args.label, args.max_usd,
                           args.allow_unsigned, keys)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{args.label}-{model}-{args.reasoning}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    meta = result["meta"]
    print(f"\nWrote {out}\nTotal ${meta.get('total_cost_usd', 0):.2f}" + (f"  STOPPED: {meta['stopped']}" if meta["stopped"] else ""))
    from benchmarks.report import format_table, summarise
    print("\n" + format_table([summarise(result)]))
    return out


if __name__ == "__main__":
    main()
