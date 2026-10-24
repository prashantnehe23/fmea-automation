# ADR-022: Agent Roster After Goal-Based Discovery

**Status:** Draft (awaiting engineer approval)  **Date:** 2026-10-24  **Backlog:** B-035

## Context
ADR-015 to ADR-019 redesign discovery, classification, context and remediation, but the existing agents they do not mention have no stated future, and some now overlap:

| Agent | Today | Problem under the new design |
|---|---|---|
| Controls assessor | one batched call; assumes weak controls unless the code shows otherwise | duplicates what the verifier observes along the exploit path |
| Scenario linkage | reads only the first 12,000 characters of the code | cannot reason about a real repository; overlaps the chain composer |
| Actuary | scores S/O/D from claims | has no verified evidence or business-specific catastrophic outcomes |
| Validator | reviews claims and may change scores by up to ±2; never sees the code | existence is now the verifier's job; calibration still needs evidence |
| LLM judge | grades the saboteur, actuary, validator and SRE outputs | those outputs change; nothing grades discovery quality |
| Remediator | writes a diff, then a full re-scan to compute before/after RPN | a full re-scan is far more expensive in deep mode and proves little about the specific exploit |
| Chat | knows findings and code | cannot answer "what was not examined?" or "why did you refute X?" |
| Learning memory | keyword categories and a count-based "aggression level" | replaced by root-cause domains and coverage/yield signals |

## Decision
1. **Controls assessor** is folded into the verifier: controls observed on the path and gaps become fields of the verified finding. The standalone batched agent is retired in Standard and Deep depth and kept in Quick.
2. **Scenario linkage** is replaced by the chain composer plus deterministic grouping of findings that share a surface or sink anchor, working through the code tools rather than a 12,000-character excerpt. Quick keeps the old agent unchanged.
3. **Actuary** stays the scorer, but scores *verified findings* and receives the exploit narrative, observed controls and the Business Profile's catastrophic outcomes. Its band comes from ADR-020.
4. **Validator** is re-scoped to a calibration reviewer **with code access**: it checks S/O/D against verified evidence, no longer judges whether a finding exists, and is bound by the severity guardrails of ADR-020.
5. **LLM judge** grades the new artifacts (coverage justification, attempt logs, refutation reasoning, corrective and preventive action quality), with rubrics held as data.
6. **Remediator** closes the loop: after a patch is generated the verifier re-attempts the exploit variants against the patched code, yielding `fix_verified` or `fix_not_effective` (recorded in the finding lifecycle, ADR-019). This replaces the full re-scan for before/after comparison.
7. **Chat** gains read tools for the coverage ledger, attempt logs and residual risk, and proposals to re-open a refuted finding for re-verification or to reclassify its root-cause domain; the user stays the decider (ADR-014).
8. **Learning memory** uses root-cause domains instead of keyword categories and coverage/yield instead of the aggression counter; it only seeds hypotheses for hunters within the same workspace (ADR-005).

## Alternatives considered
- Leave the old agents in place: simplest, but duplicate and contradictory outputs (two opinions on controls and existence) and wasted cost.
- Delete the validator: loses an independent check on scores; keeping it with code access is cheap.
- Keep the full re-scan after remediation: simple, but cost scales with repository size and it can pass or fail for unrelated reasons.

## Consequences
- Each retirement keeps a Quick-depth path, so the cheap behaviour users have today remains available.
- Prompts, rubrics and tests for six agents change; the benchmark (B-026) is the regression guard.
- `fix_verified` is a reasoned verdict, not an executed test (ADR-015 verification is static).
