# B-029 plan

Design record: [ADR-016](../../decisions/ADR-016-root-cause-taxonomy.md) (accepted; as-built notes added). Tests: `tests/test_root_cause.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Registry and answer coercion | `core/root_cause_domains.json`, `core/root_cause.py`, `core/models.py` | registry, coercion | [x] |
| 2 | Root-cause analyst, one call per chunk | `agents/root_cause_agent.py` | batch, garbled, error, block | [x] |
| 3 | Pipeline stage; domain to the preventive agent | `workflows/fmea_pipeline.py`, `agents/sre_agent.py` | pipeline and preventive tests | [x] |
| 4 | Persistence, chat, benchmark | caches, `core/chat.py`, `benchmarks/run.py` | round trips, chat, benchmark | [x] |
| 5 | Learning memory uses domains | `memory/*.py` | memory tests | [x] |
| 6 | Badge, filter, risk share | `frontend/src` | build, source test | [x] |
| 7 | Benchmark agreement on a live run | live run | needs spend decision | [ ] open |

Verification: `python -m pytest tests -q` (753), `npm run build`.
