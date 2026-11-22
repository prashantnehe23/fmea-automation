# ADR-016: Root-Cause Classification — Security, Architectural, Engineering, Operational

**Status:** Accepted (engineer, 2026-11-22; as-built notes below)  **Date:** 2026-10-19  **Backlog:** B-029

## Context
Findings are named scenarios with scores. Users cannot tell whether a problem is a missing security control, a design flaw, a coding defect, or an operational gap, so they cannot route it to the right owner or see systemic patterns. The only classification today is `_extract_category` in `memory/workspace_store.py`, which keyword-matches the *scenario name* (e.g. "Unauthenticated API **key** overwrite" is filed as `secrets`) and is used only for learning-memory statistics.

## Decision
1. **Four root-cause domains**, assigned per verified finding:
   - **Security**: a security control is missing or wrong (authentication, authorisation, input validation, secrets handling, cryptography).
   - **Architectural**: the structure makes the failure possible (trust boundaries, single points of failure, missing isolation, data-flow or coupling design, no idempotency).
   - **Engineering**: an implementation defect or missing engineering practice (race condition, error handling, missing tests, dependency hygiene).
   - **Operational**: runtime or process capability is missing (monitoring and alerting, backup and recovery, configuration and access management, deployment, incident response).
2. **One primary domain plus optional contributing domains.** Most real problems span domains; the primary is the layer where the *durable* fix lives ("what single change would remove this class of problem for good?"), which is more actionable than the symptom's layer.
3. **A short root-cause chain** per finding: symptom → proximate cause → root cause (one sentence each), plus a confidence value.
4. **Assigned by a dedicated Root-Cause Analyst step** after verification, so it works from verified evidence and observed controls rather than guesses made during hunting. The rubric and domain list live in a registry (data), so a domain or a sub-category can be added without code changes.
5. **Persisted and used**: stored with the finding and registry entry, shown as badges and filters, aggregated on the dashboard (e.g. "62% of critical risk is architectural"), made available to the chat (B-025) and used by the preventive-action agent (ADR-018). Keyword categories in the learning memory are replaced by these domains.

## Alternatives considered
- A single label: simple, but forces false precision on cross-domain problems.
- Map to CWE/OWASP categories only: precise for security weaknesses, but does not cover architectural or operational causes and is not owner-oriented. CWE ids may be stored as an optional tag later.
- Free-text root cause only: expressive but not aggregatable.
- Classify during hunting: cheaper, but the hunter has not yet seen controls and evidence.

## Consequences
- LLM classification can be inconsistent; the benchmark (B-026) carries expected domains so agreement is measured, and users can later correct a classification through the chat's proposal mechanism (not in the first release).
- One more agent call per finding (small output).
- Old scans have no domain; the UI shows "not classified" until rescanned.

## As built (2026-11-22, B-029)
- The rubric is `core/root_cause_domains.json`; `core/root_cause.py` reads it and tidies model answers. A new domain is a new entry there.
- `agents/root_cause_agent.py` makes **one call per chunk of ten findings**, not one per finding as the Consequences above assume; the stage runs after the actuary and before the remediation agents, so the preventive agent (ADR-018) receives the domain. It sees the finding, its evidence and the control gaps, not an exploit verification (that stage does not exist yet, B-028).
- An unknown, missing or garbled answer is `unclassified` with confidence 0; a model error leaves the chunk unclassified. A provider block still propagates.
- Stored as `root_causes` in the scan result, so both caches, the chat snapshot and the API carry it. Scans stored earlier have none and show "Not classified".
- Learning memory: `_extract_category` is removed from both memory modules; the category of a finding is its domain (`unclassified` when none). Existing memory files with the old keyword categories still load and keep their old keys.
- Interface: domain badge and filter on the Scenarios page, "Risk by root cause" (share of total RPN) on the Dashboard. Not done: a Scoring page filter, a correction flow, the legacy Streamlit dashboard.
- Findings locked in the registry are re-classified on every scan (the domain is not locked).
