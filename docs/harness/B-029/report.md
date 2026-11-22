# B-029 report

Design: [ADR-016](../../decisions/ADR-016-root-cause-taxonomy.md). Plan: [plan.md](plan.md). Date: 2026-11-22.

## Verification evidence
- `python -m pytest tests -q`: **753 passed** (33 new in `tests/test_root_cause.py`), in a separate worktree.
- `npm run build`: built. No browser check of the badge, filter, root-cause block or dashboard card.

## Acceptance criteria
Met with tests: primary domain, contributing domains, chain and confidence per finding; registry-driven domains (a fifth domain added by file only); fallback for unknown domains; chat text and detail tool; benchmark findings carry the domain; keyword matching removed from memory with old files still loading; old scans show "Not classified". **Open:** benchmark root-cause agreement against `truth.json` (needs a live run; the scorer already measures it). Interface criteria are met by build and source checks only.

## Review
Fresh-subagent review. **Critical, fixed:** the analyst's results were keyed by the finding's name before the locked-name rename step, so recurring (locked) findings lost their domain in the result, chat, benchmark and memory; results are now aligned by position after the rename (test with a real rename). Important, fixed: a stale filter could hide the whole table; scanned text now reaches the analyst as marked data; failures are logged and names matched trimmed. Also fixed: registry cached and validated with a clear error; the root-cause chain is shown in the scenario detail.
Minor, left: old memory files keep their old keyword keys beside the domain keys; "Unclassified" appears as a pattern in the learning prompt; the estimate adds one shared call but the analyst makes one per chunk of ten; no Scoring page filter; interface tests are source checks.

## Release notes
- **Behaviour change:** one extra model call per chunk of ten findings; the preventive agent is shaped by the domain; learning-memory categories become domains.
- **Migration:** none. **Rollback:** revert the merge.
- **Monitor:** share of findings left "Not classified" (analyst failures are logged), cost of the root-cause stage.
