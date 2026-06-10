# ADR-005: Memory Architecture — Four-Level Compounding Intelligence

**Status:** Accepted  
**Date:** 2026-05-24  
**Deciders:** Platform team

---

## Context

The core product claim is that the tool improves in its understanding of failure modes and
their effects the more it is used. This requires a memory architecture that is more than a
cache — it must be a compounding intelligence layer that learns from expert signals and
propagates that learning to future scans.

Without this, the tool is a stateless LLM wrapper. With it, the tool becomes a system that
accumulates proprietary knowledge about how failure modes behave in real architectures,
validated by real security engineers.

---

## Decision

**Four-level memory architecture**, each level feeding into the next.

---

### Level 1 — Component Memory (Implemented)

**What it stores:** Locked failure mode names, RPN scores (S/O/D), embeddings.

**What it does:** Ensures determinism. Same component rescanned → same failure modes,
same RPN scores. LLM non-determinism is completely eliminated for known components.

**Learning signal:** None at this level. Pure replay.

---

### Level 2 — Expert Calibration Memory (Partially implemented — audit trail exists, learning loop not yet closed)

**What it stores:** Every human RPN adjustment: failure mode, original S/O/D, adjusted S/O/D,
justification text, security engineer identity, date, scope level at which the adjustment
was made.

**What it does:** Feeds expert knowledge back into the actuary's priors. If a security
engineer with domain expertise consistently rates "JWT bypass" as Severity 9 (not the LLM's
Severity 7) across multiple components, the actuary should learn this prior and apply it
automatically to new components with JWT bypass failure modes.

**Learning signal:** Human RPN adjustments with justification text. The justification is
particularly valuable — it is labelled reasoning, not just a number change.

**Current gap:** Adjustments are stored in the audit trail but not yet fed back into the
actuary prompt as learned priors. This must be implemented.

---

### Level 3 — Cross-Component Pattern Memory (Not yet implemented)

**What it stores:** Architectural pattern fingerprints mapped to failure mode distributions.
Example: "components that call external payment APIs without circuit breakers" → failure mode
"race condition in payment processing" observed in 78% of cases, typical RPN 340-380.

**What it does:** When a new component is scanned that matches a known architectural pattern,
the saboteur is seeded with the historically observed failure modes for that pattern. The LLM
still generates and validates, but it starts from an informed prior rather than from zero.

**Learning signal:** Each new scan result. When the same architectural pattern (identified
by graph structure + component characteristics) produces the same failure mode repeatedly,
the confidence in that pattern → failure mode mapping increases.

---

### Level 4 — Cross-Customer Anonymised Intelligence (Future)

**What it stores:** Anonymised aggregate: architectural pattern → failure mode distributions
across all customers. Customer identity is stripped; only structural patterns are retained.

**What it does:** A new customer's first scan is informed by every scan ever run across the
platform. This is the network effect moat. Each customer contribution makes the tool better
for every subsequent customer.

**Privacy boundary:** Only structural/technical patterns are shared — never customer names,
code content, or business context. Patterns are abstracted to graph signatures before
aggregation.

---

### The feedback loop

```
Component scan
  → Failure modes identified (Level 1 writes)
  → Expert adjusts RPN with justification (Level 2 writes)
  → Remediation applied to codebase
  → Rescan: before/after RPN delta computed
  → Outcome stored: did the remediation actually reduce risk?
  → Level 2 learns: which remediations are effective for which failure modes
  → Level 3 learns: which architectural patterns produce which failure modes
  → Level 4 aggregates anonymised signal across customers
```

The loop is currently **open at the outcome end** — we capture before/after RPN delta but do
not yet route it back into remediation effectiveness memory. Closing this loop is the next
significant memory investment.

---

## Consequences

- **Positive:** The tool compounds. Each scan is more accurate than the last.
- **Positive:** Expert knowledge is not siloed in individual engineers' heads — it is
  systematically captured and propagated.
- **Positive:** Level 4 creates a network effect that is genuinely defensible. Competitor
  tools starting from zero cannot replicate accumulated pattern knowledge.
- **Negative:** Level 2 learning requires careful prompt engineering to avoid the actuary
  overfitting to historical adjustments and missing novel failure modes.
- **Negative:** Level 4 requires privacy-preserving aggregation infrastructure. Must be
  designed with legal review before implementation.
- **Risk:** If expert calibration signals are low quality (engineers adjusting RPNs without
  real domain knowledge), Level 2 learning degrades. Mitigation: weight signals by
  engineer's track record and require justification text before an adjustment is accepted
  into the learning corpus.

---

## Superseded by

Nothing. Active.
