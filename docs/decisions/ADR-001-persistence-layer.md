# ADR-001: Persistence Layer — SQLite over PostgreSQL / DuckDB / MongoDB

**Status:** Accepted  
**Date:** 2026-05-10  
**Deciders:** Platform team

---

## Context

The platform needed a persistence layer for: scan results, scenario registries (locked failure
modes + embeddings), evaluation history, and workspace metadata. The choice of database drives
dependency overhead, operational complexity, and the migration path to cloud multi-tenancy.

Four options were evaluated.

---

## Options Considered

| Option | Type | Extra install | Server | Vector search |
|---|---|---|---|---|
| **SQLite** | Embedded relational | None (stdlib) | No | Manual cosine (Python) |
| PostgreSQL + pgvector | Server relational | psycopg2, Docker | Yes | Native indexed ANN |
| DuckDB | Embedded analytical | pip install duckdb | No | No |
| MongoDB | Document store | pymongo | Yes (or Atlas) | Atlas only |

---

## Decision

**SQLite** for the current phase.

### Rationale

1. **Zero dependency overhead.** `sqlite3` ships with Python. A developer clones the repo and
   runs `streamlit run dashboard.py` with no infrastructure setup. This is non-negotiable for
   a tool intended for local and team-hosted deployment.

2. **Zero operational burden.** No server process to start, monitor, or crash. The database is
   a single file (`memory/fmea.db`) that travels with the project.

3. **ACID transactions.** Scan results and scenario locks are written atomically. No
   partial-write corruption from interrupted pipeline runs.

4. **Sufficient scale for this phase.** At 7 failure modes per scan and 1536 floats per
   embedding (float32), 10,000 scans ≈ 500 MB. Well within SQLite's practical limits.

5. **Fast enough for vector search.** With at most hundreds of locked scenarios per workspace,
   O(N) Python cosine similarity completes in under 1 ms. No index required.

6. **Isolation is clean.** The entire DB layer is in `memory/db.py`. The migration to
   PostgreSQL + pgvector requires changing only that file.

### Why not PostgreSQL + pgvector

Correct choice for cloud multi-tenant SaaS. Wrong choice for a local/team tool: requires a
running Postgres server, psycopg2 install, Docker or cloud provisioning. Adds 30 minutes of
setup friction for every new developer. Revisit when the product moves to cloud hosting.

### Why not DuckDB

Excellent for analytical queries. No native vector search. Adds a pip dependency without
providing capabilities we need that SQLite lacks.

### Why not MongoDB

Requires a server or Atlas subscription. Schema flexibility is not needed; our data model is
relational. No advantage over SQLite for this use case.

---

## Consequences

- **Positive:** Any developer can run the full platform with no infrastructure.
- **Positive:** DB file can be committed to version control for test fixtures.
- **Negative:** SQLite blocks concurrent writers. If multiple users run analyses simultaneously
  on a shared server, writes queue. Acceptable for single-user and small-team use.
- **Negative:** O(N) cosine search does not scale past ~10,000 scenarios per workspace.
- **Migration trigger:** When the product moves to cloud multi-tenancy or scenario counts
  per workspace exceed 5,000, migrate `memory/db.py` to PostgreSQL + pgvector. All callers
  are isolated behind the `db.py` interface; no other file needs changing.

---

## Superseded by

Nothing. Active.
