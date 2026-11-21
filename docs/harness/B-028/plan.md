# B-028 phase 0 plan

Design record: the phase 0 section of [ADR-015](../../decisions/ADR-015-goal-based-discovery.md) (ADR still Draft). Tests: `tests/test_discovery_phase0.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Batch planning and batch-aware scan input | `core/scan_scope.py` | batch, 1 MB, redaction, failed download tests | [x] |
| 2 | Merge helpers | `core/batch_merge.py` | merge tests | [x] |
| 3 | No cap; multi-batch pipeline; chunked shared agents; remediation limit | `workflows/fmea_pipeline.py`, `agents/saboteur.py` | pipeline tests | [x] |
| 4 | Estimate | `core/estimate.py` | estimate tests | [x] |
| 5 | API defaults, preview estimate, `max_batches` | `api/routers/github.py`, `api/schemas.py` | route tests | [x] |
| 6 | Estimate confirmation in the UI | `frontend/src/pages/ScanPage.jsx`, `api.js` | build; browser check | [x] |
| 7 | Review fixes | see report | follow-up tests | [x] |
| 8 | Benchmark re-run (recall, precision, Quick cost) | `benchmarks/` | needs real model runs | [ ] open |

Verification: `python -m pytest tests -q`; `cd frontend && npm run build`; browser check on a real large repository (preview only).
