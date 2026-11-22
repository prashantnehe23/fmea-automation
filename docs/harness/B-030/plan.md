# B-030 plan

Design record: [ADR-018](../../decisions/ADR-018-corrective-preventive-remediation.md) (accepted; as-built notes added). Tests: `tests/test_actions.py`.

| # | Task | Files | Test | Done |
|---|---|---|---|---|
| 1 | Action model; plan keeps legacy text lists | `core/models.py` | old plans load | [x] |
| 2 | Kinds, urgency, coercion, legacy mapping | `core/actions.py`, `core/llm_coercion.py` | coercion and urgency tests | [x] |
| 3 | Corrective and preventive agents, parallel stage | `agents/corrective_agent.py`, `agents/preventive_agent.py`, `agents/sre_agent.py` | agent, parallel, usage, block tests | [x] |
| 4 | Evaluator, judge, remediator, chat, estimate | `agents/evaluator.py`, `agents/llm_judge.py`, `agents/remediator.py`, `core/chat.py`, `core/estimate.py` | evaluator, judge, remediator, chat tests | [x] |
| 5 | Mitigations page, api mapping, legacy dashboard | `frontend/src`, `dashboard.py` | no-roadmap scan, build | [x] |
| 6 | Docs, backlog, B-010 superseded | `docs/` | backlog test | [x] |
| 7 | Cost before and after on a real scan | live run | needs spend decision | [ ] open |

Verification: `python -m pytest tests -q` (730), `npm run build`.
