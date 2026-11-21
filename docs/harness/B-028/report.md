# B-028 phase 0 report

Design: ADR-015 phase 0 section. Plan: [plan.md](plan.md). Date: 2026-11-21.

## Verification evidence
- `python -m pytest tests -q`: **617 passed** (32 new in `tests/test_discovery_phase0.py`).
- `npm run build`: built.
- Browser, real repository `anthropics/anthropic-sdk-python` (3,124 files): the scan page asked "This repository needs 5 passes", about 58 calls, roughly $2.90 with gpt-5.1 against $0.63 for one pass, 2,327 files not examined. Cancelled; no model was called.

## Acceptance criteria
Met: 7 locked plus a new vulnerability reports all 8; a 1 MB repository is fully processed or its leftovers are listed; the estimate is shown before a multi-pass scan; a single-batch scan makes the same calls as before.
**Unverified:** "Quick depth keeps today's cost on the existing benchmark (re-run recorded)" and "recall and precision on B-026 not worse than the last recorded run": both need real model runs that were not done (key expired; the benchmark spends credit).

## Review
Fresh-subagent review. It rated two items critical; both are addressed below or recorded as open. Findings and resolution:
1. Benchmark criteria not met: **left open**, recorded above.
2. With no cap, single-call agents lose items when given dozens of findings: **fixed** (chunks of ten for controls, linkage, actuary, validator; judge sees the ten highest-risk findings; missing control assessments are padded, never a crash).
3. No spend guard and an optimistic estimate: **mitigated** (remediation plans stop at 30 per scan, highest risk first, with a visible placeholder; the estimate gives a typical and an upper figure, names an assumed price, and follows the `max_batches` the scan will use). A USD budget guard remains phase D.
4. Selecting files skipped the estimate yet could run several passes: **fixed** (chosen files run one pass, as before).
5. Double start while the estimate loads: **fixed** (guard). Cached re-scans still show an estimate: left.
6. Extra tree listing per scan: accepted and recorded (a cache would risk stale trees and cross-test leakage).
7. Merging by quote lost distinct findings: **fixed** (merge by exact name only). A locked finding hallucinated by the wrong batch: left (the first batch wins).
8. A cap cut locked findings in later batches: **fixed** (locked findings are never cut).
9. Stored code order and cache key: **fixed** (path order whatever the batching).
10. Unknown model rates: **fixed** (`rates_known`, shown as "price assumed").
11. Controls misalignment crash: **fixed** (padding).
12. Tests: added route-level, failed-download, empty-batch, per-batch redaction, chunking, limit, cap and `max_batches` tests.
Minor left: cross-batch links in the linkage report; the UI cannot lower `max_batches`; the estimate dialog is hidden for one very large single pass.

## Release notes
- **Behaviour change:** scans from the app no longer cap findings and large repositories take up to five passes; cost rises accordingly. Check the estimate dialog before confirming.
- **Migration:** none.
- **Rollback:** revert the merge.
- **Monitor:** cost per scan (B-021) against the estimate; scans that hit the remediation limit (`remediation_limit.skipped`); fix candidates appearing after multi-pass scans.
