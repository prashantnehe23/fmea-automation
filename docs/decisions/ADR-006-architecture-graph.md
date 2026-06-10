# ADR-006: Architecture Graph — Code-Derived Dependency Graph, Not EA Tool Integration

**Status:** Accepted  
**Date:** 2026-05-24  
**Deciders:** Platform team

---

## Context

Enterprise Architecture (EA) tools — LeanIX, Sparx EA, Avolution ABACUS, Archimate-based
tools — already maintain dependency graphs and component inventories for large organisations.
The question was whether to build our own graph or integrate with existing EA tools as the
source of architecture data.

This decision also addresses the product differentiation question: if EA tools already have
dependency graphs, what is our moat?

---

## Analysis: What EA Tools Actually Do

EA tools are **documentation and portfolio management platforms**. They represent what
architects *say* the architecture is. They are populated manually, updated periodically
(quarterly at best), and reflect decisions made in PowerPoint before code was written.

Specifically, EA tools provide:
- Application portfolio inventories (what systems exist, their owners, lifecycle status)
- Business capability mapping (what capabilities does each system support)
- High-level integration maps (System A communicates with System B — via what protocol
  is often unclear or missing)
- Technology lifecycle management (EOL dates, vendor risk)
- Compliance mapping (which systems are in scope for which regulations)
- Cost and vendor management

EA tools do **not** provide:
- Code-level dependency analysis (they don't read the code)
- Interface-level change detection (they don't know what changed or when)
- Failure mode identification (they describe topology, not risk)
- Quantified risk scoring (no RPN, no severity/occurrence/detection)
- Remediation plans (they document problems, don't solve them)
- Cross-component failure mode propagation (they show edges, not what flows across them)
- Any learning or intelligence layer

**The critical gap:** EA tools describe what architects *intended*. Our tool analyses what
the code *actually does*. These diverge constantly in production systems. When they diverge,
the EA tool is wrong and our tool is right.

---

## Decision

**Build a code-derived dependency graph.** Do not use EA tools as the primary source of
architecture data.

### Rationale

**1. Code is ground truth. EA tools are documentation.**
Our graph is generated from AST analysis of actual source code. It reflects reality. An
EA tool reflects what someone drew on a whiteboard, potentially 18 months ago. The gap
between the two is where production incidents live.

**2. The failure mode intelligence is the product. The graph is the substrate.**
EA tools show you that Service A calls Service B. We show you that Service A calls Service B
*without validating the response*, that Service B *trusts the caller implicitly*, and that
this creates a privilege escalation failure mode with RPN 340 and estimated GDPR exposure
of £1.2M. The graph is necessary but not sufficient. The failure mode intelligence built
on top of it is the product.

**3. Continuous, not periodic.**
Our graph updates on every commit — or at minimum, on every scan trigger. EA tools are
updated quarterly. A graph that is 3 months stale during a fast-moving development cycle
is not useful for active risk management.

**4. Connected to the development workflow.**
Developers don't use LeanIX. Our tool is in their IDE, in their CI/CD pipeline, triggered
on every PR. The graph is maintained as a side effect of normal development. EA tools require
a dedicated architect to maintain them.

**5. Memory compounds on the graph.**
Our Level 3 and Level 4 memory (cross-component patterns, cross-customer intelligence) are
built on top of the graph. EA tools have no learning layer. Every scan we run enriches the
graph and the pattern memory. EA tools don't get smarter — they get more out of date.

---

## The right relationship with EA tools

We are **not** competing with LeanIX or Sparx. We are building the risk intelligence layer
that EA tools lack.

The correct positioning is:
- EA tools: the map (what exists, who owns it, what it costs)
- Our tool: the risk model (what can fail, how likely, what it means to the business)

**Integration opportunity (future):** If a customer already has a populated LeanIX instance,
we should be able to import their application inventory as the initial scaffold for our graph,
then enrich it with code-derived edges. This reduces onboarding time for large enterprises
while maintaining our code-level ground truth as the authoritative source.

This integration should be **import only** — we read from EA tools to bootstrap, we never
write back to them. Our graph is the live, accurate version.

---

### What our graph contains that EA tools do not

| Data | EA Tool | Our Graph |
|---|---|---|
| Component inventory | ✓ (manually maintained) | ✓ (code-derived, always current) |
| High-level integration edges | ✓ (manually maintained) | ✓ (code-derived) |
| Function-level call edges | ✗ | ✓ |
| DB tables per component | ✗ | ✓ |
| External API calls per component | ✗ | ✓ |
| Shared secrets / config dependencies | ✗ | ✓ |
| Interface change history | ✗ | ✓ |
| Failure modes per component | ✗ | ✓ |
| Cross-component failure propagation | ✗ | ✓ |
| RPN scores, severity/occurrence/detection | ✗ | ✓ |
| Remediation plans | ✗ | ✓ |
| Expert calibration history | ✗ | ✓ |
| Pattern memory (architecture → failure mode) | ✗ | ✓ |

---

## Consequences

- **Positive:** Ground truth advantage. Our graph cannot go stale because it is derived
  from the code, not from documentation.
- **Positive:** No dependency on third-party EA tool subscriptions or APIs.
- **Positive:** Failure mode intelligence is unique — no EA tool provides this.
- **Negative:** We must build the graph from scratch per customer. EA integration (future)
  can accelerate initial onboarding for customers who have populated EA tools.
- **Negative:** AST-based interface extraction requires language-specific implementations.
  Python first; other languages follow on demand.
- **Strategic risk:** If a major EA tool (LeanIX, ServiceNow) adds failure mode analysis
  and code-level graph derivation, the moat narrows. Mitigation: the memory layer (Levels
  2-4) is not replicable from a standing start — it requires accumulated scan history,
  expert calibration data, and cross-customer anonymised patterns. The longer we run,
  the harder it is to replicate.

---

## Superseded by

Nothing. Active.
