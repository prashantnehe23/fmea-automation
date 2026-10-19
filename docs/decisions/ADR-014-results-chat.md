# ADR-014: Results Chat — Persistent Context with On-Demand Code Access

**Status:** Accepted (approved by engineer 2026-10-19)  **Date:** 2026-10-19  **Backlog:** B-025

## Context
Users need to ask follow-up questions about scan results (why, how exploitable, challenge a score) and, if they agree, change scenarios and rankings. LLM APIs are stateless: an open connection cannot remember the scanned code or findings. Re-sending the code with every question is costly (a repo-sized scan is ~57k input tokens) and fails for large repos.

## Decisions
1. **Memory is server-side state plus a stable prompt prefix, not an open connection.** The scan's source files are persisted per scan, conversations are persisted in SQLite, and every request begins with an identical prefix (system prompt + compact findings + file index) so providers that cache prefixes can reuse it. Correctness never depends on caching.
2. **Findings always in context, code on demand.** The model reads code through allowlisted `read_file` / `search_code` tools, and full scenario detail through `get_scenario_detail`. Per-turn cost stays low and the design works for any repo size.
3. **Propose, user confirms.** The model can only *propose* score adjustments or scenario unlocks. Nothing changes until the user clicks Apply, which goes through the existing adjustment audit trail (B-001). Consistent with B-020's principle that nothing is modified silently.
4. **One thread per project, pinned to the latest scan.** Each message records the scan it concerned, so a rescan does not orphan history.
5. **Model-agnostic.** Uses the OpenAI-compatible chat + tool-calling API through the existing provider registry, the reasoning level (ADR-012) and adaptive output handling (ADR-013). A model without tool calling answers from the findings prefix.

## Alternatives considered
- Whole code in every turn: simplest and most reliable answers, but re-sends the repo each turn and breaks on large repos.
- Hybrid by size: best small-repo answers, but two code paths to build and test.
- Provider stateful APIs (e.g. response-id chaining): real server-side memory, but provider-specific and breaks model-agnosticism.
- Apply immediately with undo: fewer clicks, but a misread can alter risk rankings.
- One thread per scan: cleaner isolation, but context is lost on every rescan.

## Consequences
- Scan source code is now stored in SQLite (growth bounded by the existing per-scan size limit); it must be covered by any future data-retention and access rules (B-015).
- Tool calls add round trips and depend on model reliability; the UI shows tool activity so latency is visible.
- Scanned code is untrusted prompt content, so injection defence rests on read-only allowlisted tools and user-confirmed writes.
- Chat usage adds LLM cost per message, tracked in telemetry as agent `chat`.

## Implementation notes (phase 1, 2026-10-19)
- The database previously stored only a fingerprint stub for each scan, so full findings are now persisted alongside the source files (`scan_snapshots`, `scan_sources`), keyed by project + fingerprint. Cached rescans therefore also work with chat.
- "Pinned to the latest scan" is implemented as the newest snapshot of the project, resolved on every turn; each stored message records its snapshot id.
- Tool results stay in history (full memory of code already read) and the history is folded into a summary beyond 24k tokens. Measured on Mistral Large 4: prompt grew 7.5k -> 15.9k tokens across three turns.
- Mistral's "prefix" assistant continuation is not used (see ADR-013); chat answers cut off at the limit are continued with a plain continue message.

## Implementation notes (phase 2, 2026-10-19)
- One generator (`run_turn`) drives a turn for both the blocking and the SSE endpoint; only the LLM call differs (`call_chat` vs `stream_chat`).
- Stop = client disconnect. The async endpoint pulls events from the sync generator through a lock-guarded pump and, on disconnect or cancellation, closes it; closing triggers the save of the question, completed tool rounds and the partial answer, and closes the provider stream so generation ends.
- Validation errors (no scan, no key, empty message) are raised before streaming starts, so they keep real HTTP status codes (409/422) instead of arriving as in-stream errors.
- Chat cost is a telemetry span with agent `chat` outside any scan run and is summarised separately (`cost_summary.chat_usd`), so it never distorts "last scan" cost figures.
- Frontend: no new dependency; a small markdown component renders to React nodes only (see B-025 phase 2 trade-offs).
