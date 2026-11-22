# B-047 plan

Design record: [ADR-030](../../decisions/ADR-030-more-model-providers.md). Tests: `tests/test_more_providers.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Registry entries, endpoint and custom-model settings | `core/providers.py`, `core/costs.py` | registry, endpoint, custom model tests | [x] |
| 2 | Client per endpoint; no temperature where rejected | `core/llm.py` | request-shape tests | [x] |
| 3 | Settings API and role policy | `api/routers/settings.py`, `api/schemas.py`, `api/policy.py` | API and policy tests | [x] |
| 4 | Prices unknown, estimates, no embeddings | `core/costs.py`, `core/estimate.py`, `memory/scenario_registry.py` | cost and embedding tests | [x] |
| 5 | Settings-panel block | `frontend/src` | build, source test | [x] |
| 6 | Local scan and hosted-provider benchmark | live runs | needs a model server, a key and spend | [ ] open |
| 7 | AWS Bedrock (native adapter) | later phase | | [ ] open |

Verification: `python -m pytest tests -q`, `npm run build`.
