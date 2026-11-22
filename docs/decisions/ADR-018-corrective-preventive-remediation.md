# ADR-018: Remediation Split — Corrective and Preventive Actions; No Time-Boxed Roadmap

**Status:** Accepted (engineer, 2026-11-22; as-built notes below)  **Date:** 2026-10-19  **Backlog:** B-030 (supersedes B-010)

## Context
One SRE agent per finding produces `fixes`, `monitoring`, `resilience_upgrades`, a `roadmap_90_day` (Day 30/60/90) and Gantt-style `roadmap_tasks` with start/end days. It is the largest cost driver (8,192-token output, one call per scenario, 50-80 s each on Mistral Large 4), and mixes two different intents. Delivery timelines are decisions for SRE and product teams, who know capacity and dependencies; an LLM guessing day numbers adds false precision. The evaluator even raises an *issue* when a Day 30/60/90 phase is missing, and the judge scores roadmap fields.

## Decision
1. **Two focused agents per verified finding**, run in parallel and given the verified exploit path, observed controls and the root-cause domain (ADR-016):
   - **Corrective agent** (stop and fix the problem now): code-level fix with file/function references, containment and workarounds, data clean-up or rollback, and how to verify the fix.
   - **Preventive agent** (stop the class of problem recurring and detect it early): guardrails (tests, lint/SAST rules, CI gates), design or architecture changes, secrets and access practices, monitoring and alerting signals, runbooks and drills. Chosen by root-cause domain (an architectural root cause yields design actions, an operational one yields detection and process actions).
2. **A common `Action` shape**: id, title, detail, kind (code_fix, containment, config, test, guardrail, design_change, monitoring, runbook, process…), target (file/component), verification, owner role (developer, SRE, security, product), and an **urgency band** (`now`, `next`, `later`) derived from risk and action kind (containment first). The urgency is an ordering hint, not a date.
3. **Remove** the 30/60/90 roadmap, the Gantt task list (start/end days, dependency graph) and their evaluator and judge rules. Teams schedule delivery themselves.
4. **Compatibility:** results already stored keep their old fields; the UI maps old `fixes` to corrective actions and old `monitoring` / `resilience_upgrades` to preventive actions so earlier scans stay readable. The on-demand remediator (code diff and test) consumes corrective actions of kind `code_fix` instead of `plan.fixes[:3]`.
5. B-010 (Gantt roadmap) is superseded and closed on approval.

## Engineer decisions (2026-10-19)
- Actions keep a **now / next / later ordering band** (an ordering hint, never a date).

## Alternatives considered
- Keep one SRE agent and only drop the roadmap: simpler, but keeps the mixed intent and the large single output.
- Three agents (corrective, preventive, detective): finer, but detection fits naturally inside preventive and a third call adds cost; can be split later.
- Keep an optional roadmap view for executives: contradicts the decision to leave delivery planning to the teams; an exporter can still produce one from the actions.

## Consequences
- Prompts get smaller and more specific; two calls per finding replace one large call, and they run in parallel.
- Executives lose the generated timeline; the platform now provides the action backlog only.
- Removing fields touches models, coercion, evaluator, judge, the React Mitigations page, the legacy Streamlit dashboard and tests.

## As built (2026-11-22, B-030)
- `core/actions.py` holds the kinds, owner roles, urgency table and answer coercion; `agents/corrective_agent.py` and `agents/preventive_agent.py` each make one model call; `agents/sre_agent.py` runs both in parallel (a copy of the scan's context per worker, so usage, the spend limit and stage tracking still apply; a provider block or spend limit in either raises out of the stage).
- Kinds as built: corrective `code_fix`, `containment`, `config_change`; preventive `guardrail`, `design_change`, `monitoring`, `runbook`. The wider list above (test, process, config) was narrowed to what the two agents can tell apart. Owner roles: developer, security, sre, product.
- Urgency is derived in code from the finding's priority and the action kind (containment is `now` for Critical, High and Medium; fixes are `now` for Critical and High). Never a date.
- Root-cause domain: `run_preventive_agent` accepts a domain and shapes its focus by it. The pipeline passes the domain from the root-cause analyst (B-029) when one was assigned; for an unclassified finding the prompt asks the model to decide it itself.
- Plans stored before this change keep `fixes`, `monitoring` and `resilience_upgrades`; `plan_actions` maps them (fixes to corrective, monitoring and resilience upgrades to preventive) for the UI, chat, judge and remediator. Their stored `roadmap_*` fields are ignored on load.
- Cost: two calls per finding of up to 4,096 tokens each instead of one of 8,192; `core/estimate.py` counts two. The before/after cost on a real scan has not been measured.
