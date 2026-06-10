# ADR-002: Workspace Hierarchy — Organisation → Portfolio → Project → Component

**Status:** Accepted  
**Date:** 2026-05-24  
**Deciders:** Platform team

---

## Context

The original data model had a flat two-level structure: `customer` → `project`. This was
sufficient for a single-user tool but insufficient for enterprise or multi-tenant use where
a single organisation has multiple business units, each containing multiple applications,
each containing multiple code components.

The hierarchy also drives the scope of risk aggregation in the dashboard: executives need
portfolio-level views, risk managers need project-level views, developers and SREs need
component-level views.

---

## Decision

Four-level hierarchy: **Organisation → Portfolio → Project → Component**

| Level | Meaning | Example |
|---|---|---|
| Organisation | Top-level tenant. Multi-tenancy boundary. | Acme Financial Services |
| Portfolio | Business unit or product line. Risk aggregation unit for executives. | Payments Platform |
| Project | A specific application or service. | Payment Gateway API |
| Component | A specific code scope within a project. Scan unit. | checkout_service.py |

### Why four levels, not three

Three levels (Org → Project → Component) collapses the business unit concept. In a large
organisation, an executive cares about "Payments Platform risk" as a whole — not the risk of
each individual service. The Portfolio level is the natural aggregation boundary for executive
reporting and for correlating risks across related services (shared infrastructure, shared
secrets, shared compliance obligations).

### Why "Component" not "Workspace"

"Workspace" was the original term but it collided with the broader concept of a scan context.
"Component" is precise: it is the unit of code that gets scanned. A component maps to a
file, a module, a microservice, or any coherent code unit the developer defines.

### Normalised DB schema (Option B)

Four separate tables with foreign key relationships, not a flat table with four columns.
This was chosen over a flat schema because:
- Enables proper scoping of permissions (RBAC) per level
- Enables portfolio-level queries without full table scans
- Enables the architecture graph to attach edges at the correct level (Component edges,
  Project-level architecture context)
- Clean migration path: add columns to each table independently

```sql
organisations (id, name, slug, created_at)
portfolios    (id, org_id FK, name, created_at)
projects      (id, portfolio_id FK, name, created_at, architecture_context_json)
components    (id, project_id FK, name, interface_hash, created_at)
```

---

## Consequences

- **Positive:** Dashboard scope switching (Component / Project / Portfolio / Org) maps
  directly to hierarchy levels — no impedance mismatch.
- **Positive:** Scenario registry is scoped to Component; architecture context is scoped
  to Project. Both are the correct granularity.
- **Positive:** RBAC can be introduced per level without schema changes.
- **Negative:** Four-table join required for queries that span the full hierarchy.
  Acceptable given SQLite performance characteristics and expected data volumes.
- **Migration from old schema:** `customer` field maps to Organisation; `project` maps to
  Project; `function` maps to Component. Portfolio is new and must be populated on migration.

---

## Superseded by

Nothing. Active.
