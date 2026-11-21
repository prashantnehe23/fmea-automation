# B-012 plan

Design record: [ADR-029](../../decisions/ADR-029-pull-request-check.md). Tests: `tests/test_pr_check.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Scan without touching the record | `workflows/fmea_pipeline.py` (`persist=False`) | record-untouched test | [x] |
| 2 | Spend limit | `core/budget.py`, `core/llm.py` | budget tests | [x] |
| 3 | Verdict against the baseline; comment | `core/pr_check.py`, `memory/db.py` | verdict, identity, comment tests | [x] |
| 4 | API tokens, endpoint, settings | `core/auth.py`, `api/routers/ci.py`, `api/policy.py` | token, scope, config tests | [x] |
| 5 | Changed files first | `core/scan_scope.py`, `core/github_fetcher.py` | boost test | [x] |
| 6 | CI template | `docs/ci/fmea-pr-check.yml` | template tests | [x] |
| 7 | Review fixes | see report | follow-up tests | [x] |
| 8 | Run on a real repository with a real model | | needs a key and a test repository | [ ] open |

Verification: `python -m pytest tests -q`.
