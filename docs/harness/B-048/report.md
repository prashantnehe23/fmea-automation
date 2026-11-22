# B-048 phase 1, slice A report

Design: [ADR-031](../../decisions/ADR-031-frontend-test-framework.md) (test stack). Plan: [plan.md](plan.md). Date: 2026-11-22.

## Verification evidence
- `python -m pytest tests -q`: **867 passed** (10 new in `tests/test_findings_view.py`), in a separate worktree.
- `cd frontend && npm test`: **23 passed** in 4 files (Vitest, Testing Library, jsdom): findings rules, the page with test fixtures, the page with the real result shape run through `normalizeScanResult`, and a smoke test.
- `npm run build`: built. **No look in a real browser**: by the engineer's decision, behaviour is checked by the JS tests; jsdom has no layout or CSS, so visual correctness of the new page is unchecked.

## Acceptance criteria (phase 1, slice A)
- [x] A finding is reviewable from one view: impact, score with reason, evidence, root cause, fix, source, history (component tests)
- [x] The watchlist lists every severity 9+ finding including locked ones; old stored scans show current bands without migration (tests: `refresh_bands` applied to every reader of a stored scan)
- Not in this slice: navigation restructure, one icon set, accessibility pass with an automated axe check, first-run flow, scan history, dashboard watchlist.

## Review
Fresh-subagent review (it read the code but did not run the tests). **Important, fixed:** the recomputed bands applied only when a project's scan was opened, so chat, the PR check and the SARIF export could disagree with the screen (now applied in `get_latest_snapshot`); `refresh_bands` could raise on a stored risk with missing scores and duplicated the exploit rule (now tolerant, uses `exploit_confirmed_from`); an adjusted score kept the old band reason (now says it was adjusted); state buttons offered the state a finding was already in, which the server refuses (now hidden); stale selection, filters, history and a late answer for another project (reset on project change, late answers ignored). Also fixed: `aria-current` instead of `aria-pressed`, focus moves to the finding when selected, the priority filter lists only priorities present. Added a test that feeds the page the server's result shape through the app's own mapping.
**Left:** a severity 9+ finding appears twice (watchlist and list), as two buttons with the same name; no `Low` band is produced by the current rules, so a Low filter appears only for old data; the watchlist threshold 9 is duplicated in `findingsModel.js` rather than shared with `core/priority.py`.

## Release notes
- **Behaviour change:** a new Findings step in the navigation (step numbers shift by one); stored scans are shown with today's bands; the frontend gains dev dependencies (`vitest`, Testing Library, `jsdom`) and `npm test`.
- **Migration:** none. **Rollback:** revert the merge.
- **Monitor:** reports of bands that differ from an older view of the same scan.
