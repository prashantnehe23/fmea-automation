# ADR-004: Scan Strategy — Interface-Aware Incremental Scanning

**Status:** Accepted  
**Date:** 2026-05-24  
**Deciders:** Platform team

---

## Context

Three scan strategies were evaluated when a component is added or updated:

- **Option A:** Full project rescan on any change. Always accurate, does not scale.
- **Option B:** Full rescan on component add; component-only rescan on update. Simple, but
  stale architecture context when a component's interface changes.
- **Option C:** Interface-aware incremental scanning. The change discriminator is whether
  the component's *interface* changed, not whether any file changed.

The product's core value proposition — a continuously accurate architectural risk model — makes
Option C the only choice that earns that claim.

---

## Decision

**Option C: Interface-aware incremental scanning.**

### Key principle

A component's *interface* is what other components depend on. Internal implementation changes
do not affect the risk profile of neighbouring components. Interface changes do.

**Interface definition for a component:**
- Exported function signatures (name, parameters, return type)
- API endpoints exposed (route, method, request/response schema)
- Database tables read/written
- External services called (URLs, queues, topics)
- Imported modules from other project components
- Data schemas produced or consumed

### Trigger logic

**Component ADD:**
→ Architecture context rebuild (new node in graph, topology changed)
→ Scan new component with full project context
→ Re-scan direct neighbours (they may interact with the new component)

**Component UPDATE — interface unchanged** (same signatures, same imports, same API surface):
→ Architecture context still valid — skip Layer 1
→ Re-scan changed component only
→ Neighbours unaffected — locked scenarios preserved

**Component UPDATE — interface changed:**
→ Partial architecture context rebuild: update this node's entry in the graph
→ Re-scan changed component
→ Re-scan direct neighbours: cross-component failure modes may have changed
→ Cascade to indirect dependencies only if the interface change propagates transitively

**Component DELETE:**
→ Full architecture context rebuild
→ Re-scan all components that previously had edges to the deleted component

### Interface change detection

Each component stores an `interface_hash` in the DB: a deterministic hash of its interface
elements. On each scan trigger, the extractor recomputes the hash. Hash match → interface
unchanged. Hash mismatch → interface changed, trigger neighbour cascade.

### Conservative default

If the interface extractor is uncertain (e.g., dynamic imports, runtime-injected dependencies,
non-Python files), treat the component as interface-changed. Over-rescanning wastes LLM calls.
Under-rescanning misses failure modes. Only one of those is recoverable.

### Three-layer scan architecture

```
Layer 1 — Project Architecture Context (runs on ADD or interface change)
  Input:  all project files
  Output: component inventory, dependency edges, trust boundaries,
          external integrations, shared secrets/config
  Stored: projects.architecture_context_json

Layer 2 — Component FMEA (runs per component on any change)
  Input:  component code + Layer 1 context
  Output: failure modes, RPN scores, remediations
  Stored: scenarios table, scans table

Layer 3 — Cross-component failure modes (runs on ADD or interface change)
  Input:  Layer 1 context, interface boundaries
  Output: failure modes that span component boundaries
  Stored: scenarios table, scoped to Project level (not Component)
```

### Implementation phasing

| Phase | Scope | When |
|---|---|---|
| 1 | Full graph infrastructure + Python AST extractor | Now |
| 2 | SQL/ORM schema extraction (DB tables per component) | Next |
| 3 | YAML/config/env extraction (shared secrets, feature flags) | Next |
| 4 | Multi-language support (JS/TS, Go, Java) | Per language, on demand |

Non-Python files in Phase 1 are treated as opaque nodes with conservative (always interface-changed) assumption.

---

## Consequences

- **Positive:** Neighbours of unchanged components keep locked scenarios — zero LLM calls
  for the stable parts of the system. Cost scales with actual change, not project size.
- **Positive:** Cross-component failure modes are surfaced — the class of vulnerabilities
  that cause the most severe production incidents.
- **Positive:** The architecture graph compounds over time: each scan enriches the model
  of how the system works.
- **Negative:** Python AST interface extraction adds a pre-scan step. Complexity is bounded
  and well-understood but non-trivial to implement correctly for all Python patterns.
- **Negative:** Dynamic code patterns (monkey-patching, `importlib`, late binding) may
  produce incomplete interface hashes. Conservative default mitigates but does not eliminate.
- **Risk:** The graph can become inconsistent if a bulk rename or refactor changes many
  component names simultaneously. Mitigation: detect when >50% of graph nodes change in a
  single operation and trigger a full rebuild rather than incremental update.

---

## Superseded by

Nothing. Active.
