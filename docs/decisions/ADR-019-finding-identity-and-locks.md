# ADR-019: Finding Identity, Lifecycle and Lock Semantics

**Status:** Accepted (engineer, 2026-11-21)  **Date:** 2026-10-19  **Backlog:** B-031 (revises parts of ADR-003 and B-001)

## Context
The scenario registry (ADR-003) locks scenario *names* and S/O/D scores so a rescan of similar code gives stable results; scenarios are matched by name and, failing that, by embedding similarity. This design fits one-shot generation capped at N scenarios. With goal-based discovery (ADR-015):
- locked scenarios must not consume the discovery budget or hide new findings;
- findings carry more than a name (threat class, surface anchor, verdict, evidence, root-cause domain);
- a rescan can now *refute* something that used to be a finding, which is useful (a fix landed) and must not be silently kept or silently dropped;
- repeated scans of the same code must still produce the same results (cache by fingerprint stays).

## Decision
1. **Stable finding identity** = hash of (threat class, surface anchor, sink anchor), with the existing embedding match as fallback when code moves. Names become display text.
2. **Lifecycle states**: `new` → `confirmed` → `fixed` (a later scan refutes it with evidence), `regressed` (confirmed again after fixed), `accepted` (user accepts the risk), `unresolved` (could not be decided). State changes are recorded with the scan that caused them.
3. **Locks stabilise scores, not discovery.** A locked finding keeps its S/O/D (as today, with expert adjustments from B-001 and B-025 overlaid). Discovery always runs over the whole coverage ledger; locked findings do not count against any cap, and new findings are added regardless of how many are locked.
4. **Locked but now refuted** findings become `fixed` candidates and are shown for confirmation instead of being re-asserted; the user can unlock (B-025 provides a per-scenario unlock).
5. **Determinism:** identical code (fingerprint) returns the cached result as today. For changed code, scores of locked findings are stable; new findings may vary between runs, which is recorded as drift in the evaluation (B-032).

## Alternatives considered
- Keep name-based locks: simple, but names drift under the more varied output of verifier agents.
- Drop locks entirely: removes stability that users value (B-001).
- Treat each scan as independent: loses regression tracking and expert score continuity.

## Consequences
- A migration maps existing registry rows onto the new identity (best effort by name and embedding).
- The registry gains lifecycle columns; chat tools and the dashboard can answer "what got fixed or regressed since the last scan".

## Amendment made during implementation (2026-11-21)
- **Identity today is the code quote, not (threat class, surface, sink).** The current pipeline has no threat class or anchors, so identity is a hash of the evidence quote with paths, line numbers and quoting removed (at least 20 characters; generic quotes such as `return x` give no identity). A rename of the scenario or a file move keeps it. Two findings never share an identity: a duplicate quote leaves the newer finding without one, and an ambiguous match is never guessed. The threat class joins the hash when B-028 supplies it.
- **A seventh state, `fix_candidate`,** holds a finding the latest scan did not reproduce until a person confirms the fix (`fixed`) or says it is still there (`confirmed`). A scan never sets `fixed` itself. Because the current detection is a single model pass, absence is weak evidence; the evidence-backed refutation arrives with B-028.
- **Cap:** locked (expected) findings do not count against `max_failure_modes`: the saboteur is asked for the cap plus the number of expected findings. B-028 phase 0 removes the cap altogether.
- **Fixed findings and fix candidates stay in the registry** (scores kept, used for matching and regression) and are offered to the model as anchors to report only if present again.
- **Scan outcomes apply only if a finding is still in the state the scan started from,** so a person's decision made during a scan is never overwritten and two scans do not double-record. A cache hit also applies the rules (a revert to old code after a fix is a regression) and replaces the stale lifecycle fields stored with the cached result.
- **`regressed` stays until a person acts** (mark fixed, accepted or confirmed).
