# B-042 plan

Design record: [ADR-026](../../decisions/ADR-026-deployment-model.md) (accepted 2026-11-21). Tests: `tests/test_deployment.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Data directory on one volume (`FMEA_DATA_DIR`) | `core/paths.py`, `memory/db.py`, `core/settings.py`, `core/workspace.py`, `memory/{workspace_store,eval_store,analysis_cache,learning_memory}.py` | `test_data_dir_env_moves_every_runtime_file`, `test_default_locations_are_unchanged_without_data_dir` | [x] |
| 2 | Provider keys encrypted at rest | `core/secrets.py`, `core/providers.py`, `requirements.txt` | `test_key_is_not_readable_on_disk_but_round_trips` and 5 more | [x] |
| 3 | Per-scan (thread-local) usage counters | `core/llm.py` | `test_two_concurrent_scans_keep_separate_call_counts`, `test_a_scan_does_not_see_another_threads_calls` | [x] |
| 4 | Retention and delete on request | `core/retention.py`, `memory/db.py`, `core/chat.py`, `api/routers/workspace.py`, `api/main.py` | `test_purge_*`, `test_delete_sources_*`, `test_zero_retention_*`, `test_retention_days_*` | [x] |
| 5 | `/api/health` with version and database status | `api/main.py`, `core/version.py` | `test_health_*` | [x] |
| 6 | API serves the built frontend | `api/main.py` | `test_built_frontend_is_served_and_api_routes_still_win` | [x] |
| 7 | Dockerfile, compose, `.dockerignore` | `Dockerfile`, `docker-compose.yml`, `.dockerignore` | `test_container_files_follow_the_adr`; image build and container run (manual, see report) | [x] files; run: see report |

Verification command: `python -m pytest tests -q`; `cd frontend && npm run build`; `docker compose up --build`.
