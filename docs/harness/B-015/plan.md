# B-015 plan

Design record: [ADR-027](../../decisions/ADR-027-authentication-roles-and-repository-access.md) (accepted, amended). Tests: `tests/test_auth.py`, `tests/test_oidc.py`, `tests/conftest.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Users, sessions, audit tables; attribution columns | `memory/db.py` | migration test, attribution tests | [x] |
| 2 | Passwords, sessions, throttle, setup | `core/auth.py`, `api/routers/auth.py` | login, setup, throttle tests | [x] |
| 3 | Policy table and app-wide check | `api/policy.py`, `api/main.py` | enumerating route tests, role matrix | [x] |
| 4 | Record the user on adjustments and proposals | `api/routers/scoring.py`, `api/routers/chat.py`, `core/chat.py` | attribution tests | [x] |
| 5 | Latest scan from the server | `memory/db.py`, `api/routers/workspace.py` | cross-user test; browser check | [x] |
| 6 | OpenID Connect | `core/oidc.py`, `api/routers/auth.py` | `tests/test_oidc.py` | [x] |
| 7 | Frontend: login, session, role view | `frontend/src/api.js`, `App.jsx`, `LoginPage.jsx`, `Sidebar.jsx` | build; browser check | [x] |
| 8 | Review fixes | see report | `tests/test_auth.py` follow-ups | [x] |

Verification: `python -m pytest tests -q`; `cd frontend && npm run build`; browser check on a copy of the real database.
