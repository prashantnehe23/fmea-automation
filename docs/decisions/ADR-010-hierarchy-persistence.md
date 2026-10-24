# ADR-010: Hierarchy Persistence — SQLite Replaces localStorage

**Status:** Accepted  
**Date:** 2026-06-21  
**Deciders:** Platform team  
**Backlog item:** B-007

---

## Context

Portfolios and projects (the UI hierarchy) were stored exclusively in `localStorage`
under the key `fmea_hierarchy_v2`. This had three significant problems:

1. **Device-local** — clearing browser storage deleted all portfolios and projects;
   users had to rebuild the hierarchy from scratch.
2. **Not shareable** — two browser tabs, two team members, or two devices saw
   completely different hierarchies even when pointed at the same backend.
3. **Blocks multi-user** — B-015 (authentication + multi-user support) requires
   server-side state. localStorage cannot serve as the shared source of truth.

The backend already had a `workspaces` table in SQLite (ADR-001), but that table
represents a *scan workspace* (a tuple of customer + project + function used to scope
the FMEA pipeline), not the UI navigation hierarchy. Portfolios and projects are a
distinct concept that needed their own tables.

ADR-002 defined the target four-level hierarchy schema with separate tables
(`organisations`, `portfolios`, `projects`, `components`). This ADR implements the
`portfolios` and `projects` layers.

---

## Decision

Move portfolio and project persistence to SQLite via two new tables and a REST API.
`localStorage` is retained as a **read-through cache** to eliminate blank-screen flash
on page load; the API is the authoritative source of truth.

---

## Schema

```sql
CREATE TABLE IF NOT EXISTS portfolios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id   INTEGER NOT NULL REFERENCES portfolios(id),
    name           TEXT    NOT NULL,
    repo_url       TEXT,
    business_tier  TEXT    NOT NULL DEFAULT 'Tier 1',
    user_type      TEXT    NOT NULL DEFAULT 'external_customers',
    created_at     TEXT    NOT NULL
);
```

`organisations` and `components` are deferred to the B-015 (multi-user) sprint, where
organisation becomes the RBAC boundary and components become explicit scan units.

---

## API

Six new endpoints on the existing `workspace` router:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/portfolios` | Nested portfolio + project list |
| POST | `/api/portfolios` | Create portfolio |
| DELETE | `/api/portfolios/{id}` | Delete portfolio + projects |
| POST | `/api/portfolios/{id}/projects` | Create project |
| PATCH | `/api/projects/{id}` | Partial update (repo_url, tiers) |
| DELETE | `/api/projects/{id}` | Delete project |

---

## ID migration (Option A — chosen)

Old project IDs were client-generated strings (`pr_1718abc`). SQLite issues integer IDs.
On first load after this change, if the API returns an empty portfolio list but
`localStorage` contains a prior hierarchy, the frontend migrates:

1. POST each portfolio/project to the API (sequential, preserves order)
2. Remap `scanHistory` localStorage keys from old string IDs to new integer IDs
3. Clear `KEY_HIERARCHY` from localStorage (now just a cache of the API)
4. Reset active selection to `EMPTY_SEL` (old string IDs are no longer valid)

Option B (start fresh, drop old scanHistory) was rejected because it silently discards
all prior scan cache, forcing unnecessary re-scans for existing users.

---

## Frontend pattern

```
Page load → read localStorage cache → render immediately
           → GET /api/portfolios (async)
               → if portfolios returned: update state + refresh cache
               → if empty + old data in cache: run migration
               → if API unreachable: stay on localStorage cache
```

Mutations (`addPortfolio`, `addProject`, `updateProjectRepo`) are now async:
POST/PATCH to API first, then update React state and write the updated hierarchy
back to `localStorage` as the new cache value.

---

## Consequences

- **Positive:** Hierarchy survives browser storage clear.
- **Positive:** Two tabs, two users at the same backend see the same hierarchy.
- **Positive:** Unblocks B-015 (multi-user) — portfolios/projects are now server-side.
- **Positive:** onboarding on a new device auto-loads the hierarchy from the server.
- **Negative:** `addPortfolio` and `addProject` are now async; callers that fire-and-forget
  (HierarchyTree form handlers) will not see the new project until the API responds.
  Latency on localhost is sub-50 ms, so this is imperceptible in practice.
- **Negative:** A one-time migration resets the active selection (user must re-click
  their project). This happens exactly once per browser profile.
- **Migration trigger:** When B-015 ships (multi-user), add `org_id FK` to `portfolios`
  and `user_id` ownership. Only `memory/db.py` and the workspace router need changing.

---

## Superseded by

Nothing. Active.
