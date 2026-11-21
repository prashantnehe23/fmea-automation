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
| [ADR-009](ADR-009-observability.md) | Observability: Telemetry, Latency & Quality Monitoring | Accepted | 2026-06-07 |
| [ADR-010](ADR-010-hierarchy-persistence.md) | Hierarchy Persistence: SQLite Replaces localStorage | Accepted | 2026-06-21 |
| [ADR-011](ADR-011-multi-provider-llm.md) | Multi-Provider LLM via OpenAI-Compatible Registry | Accepted | 2026-10-18 |
| [ADR-012](ADR-012-reasoning-control.md) | User-Controlled Reasoning Level with Automatic Token Scaling | Accepted | 2026-10-19 |
| [ADR-013](ADR-013-adaptive-llm-output.md) | Adaptive Handling of Verbose and Truncated Model Output | Accepted | 2026-10-19 |
| [ADR-014](ADR-014-results-chat.md) | Results Chat: Persistent Context with On-Demand Code Access | Accepted | 2026-10-19 |
| [ADR-015](ADR-015-goal-based-discovery.md) | Goal-Based Vulnerability Discovery: Inventory, Hunt, Prove, Cover | Draft | 2026-10-19 |
| [ADR-016](ADR-016-root-cause-taxonomy.md) | Root-Cause Classification: Security, Architectural, Engineering, Operational | Draft | 2026-10-19 |
| [ADR-017](ADR-017-business-profile-system-map.md) | Business Profile and System Map; Untrusted README | Draft | 2026-10-19 |
| [ADR-018](ADR-018-corrective-preventive-remediation.md) | Remediation Split: Corrective and Preventive; No Time-Boxed Roadmap | Draft | 2026-10-19 |
| [ADR-019](ADR-019-finding-identity-and-locks.md) | Finding Identity, Lifecycle and Lock Semantics | Draft | 2026-10-19 |
| [ADR-020](ADR-020-severity-aware-prioritisation.md) | Severity-Aware Prioritisation and Catastrophic Guardrails | Accepted | 2026-10-24 |
| [ADR-021](ADR-021-scan-scope-and-secrets.md) | Scan Scope Transparency, Infrastructure Files and Secret Handling | Draft | 2026-10-24 |
| [ADR-022](ADR-022-agent-roster-after-goal-based-discovery.md) | Agent Roster After Goal-Based Discovery | Draft | 2026-10-24 |
| [ADR-023](ADR-023-benchmark-methodology.md) | Scan Effectiveness Benchmark Methodology | Draft | 2026-10-24 |
| [ADR-024](ADR-024-defensive-framing-and-provider-blocks.md) | Defensive-Purpose Framing Across Providers, and Handling of Provider Blocks | Draft | 2026-11-09 |
| [ADR-025](ADR-025-code-index-build-vs-adopt.md) | Code Index: Build a Thin Tree-sitter Index, Do Not Embed Graphify or CodeGraph | Accepted | 2026-11-09 |
| [ADR-026](ADR-026-deployment-model.md) | Deployment Model: Single-Tenant Self-Hosted Container with the Customer's Own Model Key | Draft | 2026-11-21 |
| [ADR-027](ADR-027-authentication-roles-and-repository-access.md) | Authentication, Roles, Server-Side Results and Repository Credentials | Draft | 2026-11-21 |
