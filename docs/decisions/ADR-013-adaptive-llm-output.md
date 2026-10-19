# ADR-013: Adaptive Handling of Verbose and Truncated Model Output

**Status:** Accepted  **Date:** 2026-10-19  **Backlog:** B-024

## Context
Agents set a small per-call `max_tokens` sized for OpenAI-style behaviour. Mistral Large 4 (reasoning off) follows the surveyor's "Tree of Thoughts" instructions by writing the full three-perspective analysis as visible text (~8k tokens on a repo-sized input) and, in testing, never emitted the requested JSON. Fixed limits then either cut the reply off or the JSON was simply absent, and the scan failed, discarding the model's analysis.

`max_tokens` is a ceiling, not a cost: only generated tokens are billed.

## Decision
`call_llm` treats an agent's `max_tokens` as its *expected* size and adapts:
1. **Wide first attempt:** budget = `max(expected x reasoning multiplier, 16384)`, capped at the model's `max_output_tokens`.
2. **Continue, don't discard:** a reply cut off while producing the answer (or any plain-text reply) is continued with a "continue exactly where you stopped" message, up to 3 times, at the model ceiling. A continuation that restarts instead of resuming replaces the partial rather than being appended.
3. **Recover the structure:** if the prompt asks for JSON and the reply is analysis without parseable JSON, the analysis is sent back with a request for only the JSON, so the work informs the answer.
4. **Salvage:** as a last resort a truncated JSON is closed at the last completed element (never keeping half-written values).
5. If nothing usable can be produced, fail with a clear message.

JSON detection is by the prompt mentioning "JSON"; plain-text prompts are never JSON-recovered.

## Alternatives considered
- Raise every agent's `max_tokens` by hand: fragile per model, and it does not help when the JSON is never emitted.
- Mistral's `prefix` continuation: tested live; Large 4 restarted the answer instead of continuing, so a plain continue message is used for every provider.
- Change agent prompts (drop Tree of Thoughts): alters behaviour for all providers; deferred, since recovery handles it.
- Switch reasoning on: costs 2.5-4x more tokens and still does not guarantee JSON-only output.

## Consequences
- A verbose model costs an extra call in the recovery path (the analysis is re-read as input), still cheaper than a failed scan.
- Runaway generation is bounded by the model ceiling (default 32768 tokens per call), not by the agent size.
- The model's visible analysis is used for the JSON but is not itself stored or shown; surfacing it is a possible later feature.
- Salvage can drop the final incomplete element; this is logged as a warning.
