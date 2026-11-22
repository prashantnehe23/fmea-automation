# B-040 report

Design: [ADR-024](../../decisions/ADR-024-defensive-framing-and-provider-blocks.md). Plan: [plan.md](plan.md). Date: 2026-11-22.

## Verification evidence
- `python -m pytest tests -q`: **689 passed** (32 new in `tests/test_provider_blocks.py`), in a separate worktree so that the running benchmark was not disturbed.
- `npm run build`: built. No browser check against a real block.

## Acceptance criteria
Met with fakes: preamble everywhere; no banned wording; block classification and no retry; plain messages and model on results; block rate in the report. **Open:** the Large 4 block rate and recall after the change (real model runs); the providers' defensive-use routes (the engineer supplies them).

## Review
Fresh-subagent review. One critical, several important findings:
1. **Critical:** the reworded aggression levels sat in a file the pipeline does not use; the live learning context (`memory/workspace_store.py`) still carried "adversarial", "APT-level red team" and "single high-impact exploit": **fixed** and the banned-wording test now covers it. Benchmarks run with empty memory, so they would have understated the real block rate.
2. A block while folding old chat history escaped as an unhandled error: **fixed**.
3. Remediator and legacy dashboard: left (documented): the remediator aborts at its first blocked fix; Streamlit shows a raw error.
4. Streaming: mid-stream error events, delta refusals and the usage of a blocked stream: **fixed**.
5. More real shapes (`invalid_prompt`); a filter word quoted in a 5xx is no longer a block: **fixed**. Plain-text refusals returned as normal answers are not detected: documented.
6. Chat chooser: the chat shows the message with a hint to open Settings; no model dropdown inside the chat.
7. Old benchmark files had no block flag: **fixed** (read through the provider's error text).
Minor left: stage is blank for chat; `clear_scan_context` is not in a `finally`; old cached results show no model badge.

## Release notes
- **Behaviour change:** every prompt starts with a short defensive-purpose paragraph (about 85 tokens per call); saboteur and chat wording changed, so results will shift. Re-run the benchmark before relying on recall numbers.
- **Migration:** none.
- **Rollback:** revert the merge.
- **Monitor:** blocked scans (`provider_blocked` telemetry errors), recall after the wording change.
