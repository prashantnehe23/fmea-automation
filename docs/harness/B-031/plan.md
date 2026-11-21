# B-031 plan

Design record: [ADR-019](../../decisions/ADR-019-finding-identity-and-locks.md) (accepted, amended). Tests: `tests/test_finding_lifecycle.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Identity from the code quote; states | `core/findings.py` | identity tests | [x] |
| 2 | Lifecycle columns, history, guarded transitions, migration | `memory/db.py` | migration, history tests | [x] |
| 3 | Registry rules; identity match; fix candidates | `memory/scenario_registry.py` | lifecycle tests | [x] |
| 4 | Cap, prompt, pipeline, cache path | `agents/saboteur.py`, `workflows/fmea_pipeline.py` | cap, cache, double-mapping tests | [x] |
| 5 | API and policy | `api/routers/findings.py`, `api/policy.py` | API, role tests | [x] |
| 6 | Scan-page panel | `frontend/src/components/FindingChanges.jsx`, `api.js` | build; browser check | [x] |
| 7 | Review fixes | see report | follow-up tests | [x] |

Verification: `python -m pytest tests -q`; `cd frontend && npm run build`; browser check on a seeded temp database.
