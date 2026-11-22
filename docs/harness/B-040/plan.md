# B-040 plan

Design record: [ADR-024](../../decisions/ADR-024-defensive-framing-and-provider-blocks.md) (accepted; as-built notes added). Tests: `tests/test_provider_blocks.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Shared preamble in the model layer | `core/prompt_context.py`, `core/llm.py` | every agent and chat carry it | [x] |
| 2 | Reword personas and learning context | `agents/saboteur.py`, `core/chat.py`, `memory/learning_memory.py`, `memory/workspace_store.py` | banned-wording test | [x] |
| 3 | Classify and raise provider blocks; no retry | `core/provider_block.py`, `core/llm.py` | classification and no-retry tests | [x] |
| 4 | Stage, telemetry and user messages | `core/telemetry.py`, `core/llm_errors.py`, routers, `core/chat.py`, `core/pr_check.py` | route, chat, check tests | [x] |
| 5 | Model on results; UI | `workflows/fmea_pipeline.py`, `ScanPage.jsx`, `ChatPanel.jsx` | build | [x] |
| 6 | Benchmark block rate | `benchmarks/run.py`, `report.py` | report tests | [x] |
| 7 | Review fixes | see report | follow-up tests | [x] |
| 8 | Large 4 block rate; recall after the change | benchmark runs | needs real model runs | [ ] open |

Verification: `python -m pytest tests -q` (689), `npm run build`.
