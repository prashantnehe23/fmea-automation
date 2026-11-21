# B-031 report

Design: [ADR-019](../../decisions/ADR-019-finding-identity-and-locks.md) (amended). Plan: [plan.md](plan.md). Date: 2026-11-21.

## Verification evidence
- `python -m pytest tests -q`: **585 passed** (22 new in `tests/test_finding_lifecycle.py`), run twice.
- `npm run build`: built.
- Browser, seeded temp database: the scan page showed "1 finding no longer reproduced. Fixed?" and "Returned after a fix: ..."; Confirm fixed moved the finding to fixed and the history recorded the admin.

## Acceptance criteria
All six met as listed in the B-031 entry of `docs/BACKLOG.md`, with two caveats: the migration was not run on a real database (it has no scenario rows), and the new prompt was never run against a real model, so how well it keeps still-present findings is unmeasured.

## Review
Security and logic review by me plus a fresh-subagent review. No critical findings. Important findings and their resolution:
1. Cache hit bypassed the lifecycle and returned stale fix candidates: **fixed** (the rules apply on a cache hit; stale fields replaced; a cached "new" finding is not confirmed by display).
2. Identity collisions swallowed new findings: **fixed** (20-character minimum; no match when several rows share a quote; duplicate quotes never stored on two findings).
3. Two failures mapping to one canonical finding: **fixed** (claimed names tracked).
4. Prompt let the model forget findings and lose their anchors: **mitigated** (fixed and fix-candidate names stay in the prompt as anchors to report only if present; real-model behaviour not measured).
5. A scan's stale snapshot could overwrite a person's decision or double-record: **fixed** (transitions apply only if the finding is still in the snapshot state).
Minor fixed: birth and removal events in the history, logged bookkeeping errors. Minor left: `regressed` persists until a person acts; the cap can return slightly more than `max_failure_modes` new findings when the model omits locked ones; names fed to the prompt are unsanitised model output; manual transitions are unrestricted (for example accepted to fixed).

## Release notes
- **Migration:** automatic; adds lifecycle columns to `scenarios` (existing rows become `confirmed`) and a `finding_events` table.
- **Behaviour change:** the saboteur prompt now lets findings whose weakness is gone drop out instead of demanding them; they become fix candidates awaiting confirmation. Re-run the B-026 benchmark before relying on recall numbers.
- **Rollback:** revert the merge; new columns are ignored by older code (which would again demand every locked name).
- **Monitor:** fix candidates piling up after rescans of unchanged code (model forgetting findings).
