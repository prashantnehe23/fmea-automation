# ADR-015: Goal-Based Vulnerability Discovery — Inventory, Hunt, Prove, Cover

**Status:** Draft (awaiting engineer approval)  **Date:** 2026-10-19  **Backlog:** B-028 (measured by B-026)

## Context
Discovery today is one LLM call. The saboteur receives the whole code, brainstorms scenarios, and is capped at `max_failure_modes` (default 7, a billing cap). Consequences found in the code review:
- No coverage notion: nothing records which entry points or threat classes were examined, so "nothing found" and "not looked at" are indistinguishable.
- No verification: `evidence` is optional and never checked; the validator reviews the *claims* and never sees the code. Hallucinated scenarios and missed real ones are both undetectable.
- The cap discards findings by design ("prioritise the highest impact"), and locked scenarios (ADR-003) consume the same cap, so with 7 locked scenarios a newly introduced vulnerability has no room.
- The attack-vector checklist covers five families; classes such as SSRF, deserialisation, path traversal, IDOR, CSRF/CORS, crypto misuse, supply chain, PII in logs and resource exhaustion are left to chance.
- Scenario linkage reads only the first 12,000 characters of the code.

The goal is that no scenario capable of a catastrophic outcome is silently lost. A tool cannot *prove* the absence of vulnerabilities, so the achievable, measurable goal is: **every part of the attack surface is examined against every applicable threat class, every hypothesis ends in an evidenced verdict, and anything not resolved is reported as residual risk rather than dropped.**

## Decision
Replace single-shot brainstorming with a coverage-driven pipeline (agents keep a goal, a plan, and a progress check):

1. **Inventory.** A surveyor builds a structured attack-surface inventory (entry points, trust boundaries, data stores, secrets, external calls, privileged operations), each item anchored to file/line. It runs twice with different prompts and the results are unioned, to reduce missed surfaces. The inventory is the denominator of the goal.
2. **Threat-class registry (data, not code).** A registry of threat classes (STRIDE-style plus concurrency, resilience, data integrity, supply chain, secrets, logging/PII, resource exhaustion, business-logic abuse), each with: applicable surface types, a *variant checklist* (e.g. for injection: parameter, header, stored/second-order), catastrophic potential, typical root-cause domain. Adding a class is a registry entry.
3. **Coverage ledger.** One cell per (surface × applicable threat class) plus one per business-specific catastrophic outcome (from the Business Profile, ADR-017). Each cell must end as `confirmed`, `refuted` (with cited controls), `not_applicable` (with reason) or `unresolved` (budget or ambiguity). `unresolved` is reported prominently as residual risk.
4. **Hunters.** For each open cell an agent forms hypotheses using only the relevant code (read through the read-only code tools of ADR-014, not the whole repository in the prompt).
5. **Exploit verifier.** For each hypothesis an agent with read-only tools tries to construct the exploit: trace entry → data flow → sink, check attacker control, authentication and mitigating controls, and **try each variant in the class playbook before refuting**. It returns a verdict, exploit steps, controls observed, and an **attempt log** shown to users as proof of effort. Every evidence quote is **mechanically verified** against the stored source (quote must exist near the cited line); failures are sent back once and otherwise downgrade the finding to `unverified`.
6. **Catastrophic handling.** A pre-mortem pass starts from each catastrophic outcome ("cheapest path to reach this in this code"). A hypothesis with potential severity ≥ 9 cannot be finally refuted by a single verifier: it needs an independent second verification (different prompt and, where configured, a higher reasoning level). A chain composer examines confirmed findings for compound paths (several moderate issues that together reach a catastrophic outcome).
7. **Convergence.** The loop ends when no cell is open and one final "what did we miss?" pass adds nothing, or a budget (USD, calls, time) is reached; remaining cells become `unresolved`. Findings are **not capped**; the former cap becomes a budget on deep analysis, never on reporting.
8. **Scan depth is a user setting** (quick = today's single pass, standard, deep), with a cost estimate and a hard budget, following the control-with-the-user principle of ADR-012.

## Engineer decisions (2026-10-19)
- Verification is **static reasoning with read-only code tools and checked evidence**; sandboxed proof-of-concept execution is out of scope for the first release.
- **Default depth is Standard; Deep is opt-in** with a cost estimate and a hard USD budget; Quick keeps today's single pass.

## Alternatives considered
- Improve the single prompt (more vectors, higher cap): cheap, but still no coverage, verification or residual-risk reporting; does not meet the goal.
- Fully autonomous agent loop (the model decides what to read and when it is done): flexible, but unbounded cost, non-deterministic, and no objective stopping rule. The ledger gives a checkable goal and bounded cost.
- Dynamic exploitation (running proofs of concept in a sandbox): strongest evidence, but needs sandboxing, language runtimes and carries real safety risk. Out of scope; a possible later ADR.
- Static analysis tools (SAST) as the engine: good precision on known patterns but weak on business logic and chaining; may be added later as an additional hypothesis source.

## Consequences
- **Cost and time rise.** Estimate (to be measured by B-026): a deep scan costs several times today's ~$0.2-0.5 and needs parallel hunters/verifiers to stay in minutes rather than the ~11 minutes a serial scan takes on Mistral today. Quick mode preserves the cheap path.
- Results become less deterministic; ADR-019 defines finding identity and lock semantics so repeated scans stay stable.
- "Verified" means reasoned from the code with checked evidence, not executed. Verdicts carry a confidence and the method.
- The learning memory's count-based "aggression level" (ADR-005) is replaced by coverage- and yield-based signals.
- Effectiveness must be measured, not asserted: B-026 provides labelled benchmark repositories and recall/precision (including catastrophic recall) before and after each phase.
