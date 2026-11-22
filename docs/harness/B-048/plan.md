# B-048 phase 1, slice A plan

Design record: [ADR-031](../../decisions/ADR-031-frontend-test-framework.md) (test stack). Tests: `frontend/src/__tests__/`, `tests/test_findings_view.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Frontend test framework | `frontend/package.json`, `vite.config.js`, `src/__tests__/setup.js` | smoke test | [x] |
| 2 | Findings rules: watchlist, filters, plain language | `frontend/src/findingsModel.js` | `findingsModel.test.js` | [x] |
| 3 | Findings page: watchlist, list, one detail view | `frontend/src/pages/FindingsPage.jsx`, `App.jsx`, `data.js` | `FindingsPage.test.jsx` | [x] |
| 4 | Current bands for old stored scans | `core/priority.py`, `memory/db.py` | `tests/test_findings_view.py` | [x] |
| 5 | Slice B: scan history and what changed | | | [ ] open |
| 6 | Slice C: navigation, icons, accessibility with axe | | | [ ] open |
| 7 | Slice D: first-run from a repository URL | | | [ ] open |

Verification: `python -m pytest tests -q`, `cd frontend && npm test && npm run build`.
