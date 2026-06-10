from pathlib import Path

from workflows.fmea_pipeline import DEFAULT_MAX_FAILURE_MODES, run_fmea

# Demo cap: predictable API cost (2 + 2*N calls, N <= this value).
DEMO_MAX_FAILURE_MODES = DEFAULT_MAX_FAILURE_MODES


def main():
    wallet_path = Path(__file__).resolve().parent / "data" / "wallet.py"
    code = wallet_path.read_text(encoding="utf-8")

    print(
        f"Demo mode: at most {DEMO_MAX_FAILURE_MODES} failure scenarios "
        f"(~{3 + 2 * DEMO_MAX_FAILURE_MODES} LLM calls including scenario linkage)."
    )
    result = run_fmea(code, max_failure_modes=DEMO_MAX_FAILURE_MODES)

    print("\n=== CONTEXT ===")
    print(result["context"].model_dump_json(indent=2))

    print("\n=== FAILURES ===")
    for f in result["failures"]:
        print(f.model_dump_json(indent=2))

    print("\n=== SCENARIO LINKAGE ===")
    print(result["scenario_linkage"].model_dump_json(indent=2))

    print("\n=== RISKS ===")
    for r in result["risks"]:
        print(r.model_dump_json(indent=2))

    print("\n=== REMEDIATIONS ===")
    for r in result["remediations"]:
        print(r.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
