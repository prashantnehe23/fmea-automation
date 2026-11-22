# B-045 plan

Design record: [ADR-028](../../decisions/ADR-028-sarif-import-export-cwe.md) (accepted 2026-11-22). Tests: `tests/test_sarif.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | CWE normaliser; `source`, `cwe`, `also_reported_by` on findings | `core/cwe.py`, `core/models.py`, `core/llm_coercion.py` | CWE and model tests | [x] |
| 2 | Parse SARIF with limits and path hygiene | `core/sarif.py` | three fixtures, hostile input | [x] |
| 3 | Merge with our findings | `core/sarif.py` | merge tests | [x] |
| 4 | Pending imports table; pipeline joins them; cache bypass | `memory/db.py`, `workflows/fmea_pipeline.py` | pipeline tests | [x] |
| 5 | Analyst returns a CWE | `agents/root_cause_agent.py`, `core/root_cause.py` | analyst tests | [x] |
| 6 | Import and export routes, policy | `api/routers/imports.py`, `api/policy.py` | API tests | [x] |
| 7 | Export validates against the official schema | `core/sarif.py`, `tests/fixtures/sarif/` | schema tests | [x] |
| 8 | Buttons and badges | `frontend/src` | build, source test | [x] |
| 9 | Real tool exports as fixtures | needs sample files | | [ ] open |

Verification: `python -m pytest tests -q`, `npm run build`.
