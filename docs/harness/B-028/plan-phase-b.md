# B-028 phase B first slice: exploit paths across components

Design record: [ADR-015](../../decisions/ADR-015-goal-based-discovery.md) (goal-based discovery), [ADR-032](../../decisions/ADR-032-model-selection-and-evals.md) (workflow changes the evidence supports). Tests: `tests/test_component_map.py`, `tests/test_path_discovery.py`, `frontend/src/__tests__/`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Component map, packets, network-position links | `core/component_map.py` | component map tests | [x] |
| 2 | Hunter, verifier, orchestrator | `agents/path_hunter.py`, `agents/path_verifier.py`, `core/path_discovery.py` | path discovery tests | [x] |
| 3 | `discovery` mode in the pipeline and both scan requests | `workflows/fmea_pipeline.py`, `api/` | pipeline and request tests | [x] |
| 4 | Findings page shows the path; Scan page offers the deep scan | `frontend/src` | JS tests | [x] |
| 5 | Live runs: seeded chain repository | `benchmarks/paths_demo.py` | the run | [x] |
| 6 | Live runs: psitransfer, MLflow server | `benchmarks/paths_demo.py` | the run | [ ] in progress (results held) |
| 7 | Locked findings across scans, configuration-table links | | | [ ] open |

Verification: `python -m pytest tests -q`, `cd frontend && npm test && npm run build`.
