# ADR-003: Scenario Identity — Embedding-Based Semantic Deduplication

**Status:** Accepted  
**Date:** 2026-05-15  
**Deciders:** Platform team

---

## Context

LLMs are non-deterministic. Even with a prompt constraint instructing the saboteur to reproduce
locked scenario names verbatim, the model occasionally renames a scenario on rescan:
"SQL Injection via login form" becomes "Login endpoint SQL injection vulnerability". These are
the same failure mode. Without deduplication, each rescan would register a new scenario,
polluting the registry and breaking RPN determinism.

Two approaches were considered: exact string matching and semantic similarity matching.

---

## Decision

**Embedding-based semantic deduplication** using `text-embedding-3-small` with cosine
similarity threshold 0.85.

### How it works

1. On first scan: each failure mode is embedded and stored in the `scenarios` table (BLOB).
2. On rescan: new failure modes not found by exact name are embedded and compared against
   all locked scenario embeddings via cosine similarity.
3. If similarity ≥ 0.85: treat as the same scenario. Rename to canonical name, restore
   locked RPN. No new scenario created.
4. If similarity < 0.85: genuinely new scenario. Register it.

### Why not exact string matching only

Exact matching is the first line of defence (the saboteur prompt constraint). It handles
the common case. Semantic matching handles the ~5% case where the LLM renames despite the
constraint. Without semantic matching, those renames register as new scenarios and the RPN
drifts.

### Why text-embedding-3-small

- Lower cost than text-embedding-3-large with sufficient precision for scenario matching
- 1536 dimensions provides rich semantic space for security/reliability concepts
- Consistent model: embeddings are stable across API versions for the same model

### Why 0.85 threshold

- Below 0.85: different vulnerability types have similarity 0.6-0.75 (e.g., SQL injection
  vs. CSRF). Setting threshold lower risks false merges.
- Above 0.85: same vulnerability described differently typically scores 0.88-0.97.
- 0.85 provides a 10-point buffer above the observed false-positive ceiling.
- Threshold is configurable (`SIMILARITY_THRESHOLD` constant) and should be tuned as
  more data is collected on false merge rates.

### The embedded text

`"{failure_mode_name}: {first_step_of_attack_chain}"` — including the first attack chain
step improves precision by anchoring the embedding to the attack vector, not just the
vulnerability category name.

---

## Consequences

- **Positive:** RPN determinism on rescan regardless of LLM naming drift.
- **Positive:** Scenario registry stays clean — no duplicate entries for the same vulnerability.
- **Positive:** O(N) cosine search is sufficient at current scale (< 1 ms for hundreds of scenarios).
- **Negative:** Requires OpenAI API call per new scenario on registration. Cost is negligible
  (~$0.00002 per embedding) but introduces an external dependency at registration time.
- **Negative:** If the embedding model is deprecated, all stored embeddings become incomparable.
  Mitigation: store the model name alongside each embedding BLOB; re-embed on model change.
- **Watch:** If a customer accumulates thousands of scenarios, consider batching embed calls
  and caching lookup results to avoid repeated embedding of the same query text.

---

## Superseded by

Nothing. Active.
