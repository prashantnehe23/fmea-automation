# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for the FMEA Platform.

An ADR captures a significant architectural decision: what was decided, why, what alternatives
were considered, and what consequences follow. ADRs are immutable once Accepted — if a decision
is reversed, a new ADR supersedes it rather than editing the old one.

## Status lifecycle
`Draft` → `Accepted` → `Superseded by ADR-XXXX` (if reversed)

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-persistence-layer.md) | Persistence Layer: SQLite over PostgreSQL/DuckDB/MongoDB | Accepted | 2026-05-10 |
| [ADR-002](ADR-002-workspace-hierarchy.md) | Workspace Hierarchy: Organisation → Portfolio → Project → Component | Accepted | 2026-05-24 |
| [ADR-003](ADR-003-semantic-deduplication.md) | Scenario Identity: Embedding-Based Semantic Deduplication | Accepted | 2026-05-15 |
| [ADR-004](ADR-004-incremental-scanning.md) | Scan Strategy: Interface-Aware Incremental Scanning (Option C) | Accepted | 2026-05-24 |
| [ADR-005](ADR-005-memory-architecture.md) | Memory Architecture: Four-Level Compounding Intelligence | Accepted | 2026-05-24 |
| [ADR-006](ADR-006-architecture-graph.md) | Architecture Graph: Code-Derived Dependency Graph over EA Tool Integration | Accepted | 2026-05-24 |
| [ADR-007](ADR-007-react-frontend.md) | Frontend: React + Vite over Streamlit Extension | Accepted | 2026-05-28 |
| [ADR-008](ADR-008-fastapi-layer.md) | API Layer: FastAPI over Direct Import / GraphQL / gRPC | Accepted | 2026-05-28 |
| [ADR-011](ADR-011-multi-provider-llm.md) | Multi-Provider LLM via OpenAI-Compatible Registry | Accepted | 2026-10-18 |
| [ADR-012](ADR-012-reasoning-control.md) | User-Controlled Reasoning Level with Automatic Token Scaling | Accepted | 2026-10-19 |
