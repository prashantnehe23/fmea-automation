# ADR-020: Severity-Aware Prioritisation and Catastrophic Guardrails

**Status:** Draft (awaiting engineer approval)  **Date:** 2026-10-24  **Backlog:** B-034

## Context
Priority is derived from RPN alone: `Critical` above 400, `High` above 200, otherwise `Medium` (inlined in `agents/actuary.py`, `agents/evaluator.py`, `workflows/fmea_pipeline.py`, plus `core.models.priority_for_rpn`). RPN multiplies Severity, Occurrence and Detection, so a catastrophic failure can score low: Severity 10 with Occurrence 3 and Detection 3 gives RPN 90, which is `Medium`. Two further paths can bury it: the validator may lower any score by up to 2 for unlocked scenarios, and an expert adjustment (Scoring page or chat) can reduce it without any special scrutiny.

The stated requirement is that no scenario capable of a catastrophic outcome is let go. Finding such a scenario (ADR-015) is not enough if it is then ranked as medium.

## Decision
1. **One prioritisation function** `priority_for(severity, occurrence, detection)` replaces every inline copy. It starts from the RPN band and applies **severity floors**: Severity ≥ 9 is never below `High`; Severity 10 with a confirmed exploit path and weak detection (Detection ≥ 6) is `Critical`. The thresholds live in one configuration table, not in code scattered across agents.
2. **The reason is stored and shown**: each finding carries `priority_reason` (e.g. "High: severity 10 floor, RPN 90 alone would be Medium").
3. **Catastrophic watchlist**: every finding with Severity ≥ 9 is listed together on the results and dashboard regardless of RPN or lock state.
4. **Guarded downgrades**: the validator cannot lower a finding's Severity below 9 unless it judges the finding unrealistic (`is_realistic = false`); an expert adjustment (Scoring page or chat proposal) that lowers Severity below 9 on a watchlist item requires a justification and is flagged in the audit trail.
5. **Derived, not stored**: priority is computed from S/O/D when read, so locked scores, adjustments and old scans all follow the current rule without a data migration.

## Alternatives considered
- Keep RPN-only bands: simple and familiar, but is the cause of the burial problem.
- Replace RPN with an Action Priority table (as in the AIAG-VDA FMEA handbook): principled, but a larger change in how users read scores; the floors are a minimal step in that direction and can evolve into a full table.
- Raise all scores of catastrophic scenarios: distorts the underlying S/O/D data users calibrate.

## Consequences
- More findings appear in High/Critical, which is intended; the benchmark (B-026) measures the share of catastrophic findings placed in High or above and watches precision.
- Existing scans change band on display (the rule is retroactive); documented in the release notes.
- Users can still disagree: Severity can be adjusted down with a stated reason.
