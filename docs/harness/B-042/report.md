# B-042 report

Design: [ADR-026](../../decisions/ADR-026-deployment-model.md). Plan: [plan.md](plan.md). Date: 2026-11-21.

## Verification evidence
- `python -m pytest tests -q`: **492 passed** (19 new tests in `tests/test_deployment.py`; one unrelated timing test, `test_db.py::test_latest_scan_returns_most_recent`, failed once in one earlier run and passed in the next four).
- `npm run build` in `frontend/`: built (unchanged by this item).
- Run as the container would, from a temp data directory (`FMEA_DATA_DIR`, `FMEA_STATIC_DIR`, `FMEA_SECRET_KEY` set), port 8010: `/api/health` returned `{"status":"ok","version":"1.0.0","database":"ok","key_storage":"encrypted"}`; `/` and an unknown client route returned the app shell (200); `/api/nope` returned 404; `/api/portfolios` returned `[]`; the database and settings were created in the data directory; saving a fake key was rejected (422) by the provider check.

## Acceptance criteria
| Criterion | Result |
|---|---|
| ADR-026 accepted | Done (engineer, 2026-11-21) |
| `docker compose up` on a clean machine and a benchmark scan | **Unverified.** Docker Desktop failed to start on the dev machine (stale `dockerInference` socket); no valid provider key. Dockerfile and compose checked by test and by the local run above only |
| Keys not readable in plain text on disk | Test passes |
| Retention and delete on request | Tests pass |
| Two concurrent scans, separate counts and costs | Tests pass (`ContextVar` per scan) |
| `/api/health` version and database status | Tests pass |

## Review
Security review by me plus a fresh-subagent review of the staged diff. No critical findings. Important findings and their resolution:
1. Thread-local counters deviated from ADR-026 (`contextvars`): **fixed** (ContextVar holding one counter object per scan; test for hand-off to worker threads).
2. Counters accumulating on pooled threads from chat calls: not fixed; nothing reads them outside a scan. Noted.
3. Retention: zero-retention purge wiped other projects' sources, no periodic purge, purge failure made the snapshot look failed: **fixed** (no purge when retention is 0 after a scan, 6-hourly background purge, separate error handling; tests).
4. Delete endpoint unauthenticated: matches every other route until B-015; recorded in README and backlog.
5. Docker criterion unverified and licence absent: recorded, not hidden.
6. Undecryptable keys silently read as missing: **fixed** (`/api/health` lists them; provider `source` is accurate; test).
7. In-memory `scan_store` keeps scan code until restart; whether caches on disk hold code unchecked: recorded in backlog and README.
Minor: NUL byte in a static path gave a 500: **fixed**. Unpinned `cryptography`, no key rotation path, import placement, compose passes only OpenAI and Mistral variables: left as is.

## Release notes
- **What changed:** see backlog entry B-042.
- **Migration:** none required. Existing plain-text keys are encrypted at startup if `FMEA_SECRET_KEY` is set. Startup now deletes stored scan source older than 30 days (findings are kept); set `FMEA_SOURCE_RETENTION_DAYS` first to change that.
- **Rollout:** set `FMEA_SECRET_KEY` (`python -m core.secrets`), then `docker compose up --build`.
- **Rollback:** revert the merge; encrypted keys in `settings.json` would need re-entering (prefix `enc:v1:`) if the code before this change reads them.
- **Monitor:** `GET /api/health` (`database`, `key_storage`, `undecryptable_keys`).
