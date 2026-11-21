# B-043 plan

Design record: [ADR-027](../../decisions/ADR-027-authentication-roles-and-repository-access.md) point 9 and its B-043 amendment. Tests: `tests/test_repo_access.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Per-owner encrypted credential store | `core/repo_credentials.py`, `core/secrets.py` | store, catch-all, undecryptable tests | [x] |
| 2 | Fetcher uses the token; plain errors | `core/github_fetcher.py`, `api/routers/github.py` | fetcher and endpoint tests | [x] |
| 3 | Credential API, audit | `api/routers/settings.py`, `api/policy.py`, `api/schemas.py` | API, admin-only, audit tests | [x] |
| 4 | Settings UI | `frontend/src/components/Header.jsx`, `api.js` | build; browser check | [x] |
| 5 | Leak checks | `tests/test_repo_access.py` | four-channel and error-path tests | [x] |
| 6 | Review fixes | see report | follow-up tests | [x] |

Verification: `python -m pytest tests -q`; `cd frontend && npm run build`; browser check.
