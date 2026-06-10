# ADR-009 — Observability: Telemetry, Latency & Quality Monitoring

**Date:** 2026-06-07  
**Status:** Accepted  
**Backlog:** B-018

---

## Context

The FMEA pipeline runs 7+ LLM agents sequentially. Before this ADR, the system was a black box:

- No visibility into which agent takes the longest (or fails)
- Validator quality scores were written to `eval_history` but never surfaced to users
- Token usage existed in `scans.llm_calls` (integer count only) — no per-agent breakdown
- A quality regression after a prompt change would go undetected until a user noticed bad output

We needed observability without adding external infrastructure (Prometheus, Datadog, etc.) — the project runs as a single FastAPI process with SQLite.

---

## Decision

**Implement lightweight structured telemetry inside the existing SQLite database.**

### Architecture

```
core/telemetry.py          Context manager agent_span()
       │                   Thread-local: scan_id, workspace_id
       │
       ▼
memory/db.py               telemetry table
  (save_telemetry_span)    scan_id, workspace_id, agent,
                           duration_ms, prompt_tokens, completion_tokens, error, ts
       │
       ▼
api/routers/telemetry.py   GET /api/telemetry/{workspace_id}
  (get_telemetry_summary)  aggregates: last_scan_latency, agent_avg_ms,
                           error_rate, quality_trend
       │
       ▼
DashboardPage.jsx          SystemHealthPanel component
                           Agent latency bars, quality sparkline, error badge
```

### Key design choices

**1. Context manager pattern (`agent_span`)**  
Each agent is wrapped in `with agent_span("saboteur"):`. The context manager:
- Records wall-clock time via `time.perf_counter()`
- Snapshots cumulative token counters from `core.llm` before and after the block to compute a per-agent delta (no interference with the running total used for billing)
- Writes to DB on exit — including in the error path
- **Swallows all exceptions**: telemetry failures cannot crash the pipeline

**2. Thread-local context**  
The pipeline runs in a thread executor (FastAPI + asyncio). Thread-local storage (`threading.local()`) carries `(scan_id, workspace_id)` for the duration of the run without polluting function signatures. Context is set at pipeline start and cleared at pipeline end.

**3. Token tracking in `core/llm.py`**  
`call_llm()` accumulates `prompt_tokens` and `completion_tokens` from `response.usage`. This is a cumulative total reset at the start of each pipeline run (alongside the call counter). The delta approach in `agent_span` allows per-agent attribution without requiring `call_llm` to know which agent it is being called from.

**4. Scan_id backfill**  
The `scan_id` is not known until after `_db.save_scan()` completes (midway through the pipeline). Spans before that point are written with `scan_id = NULL`. Once the real `db_scan_id` is available, `set_scan_context()` is called to update the thread-local so all subsequent spans (eval, registry) are linked.

**5. Quality trend from `eval_history`**  
Rather than duplicating quality data, `get_telemetry_summary()` reads directly from the existing `eval_history` table. No new data model needed for the quality trend — only a query.

**6. No external infrastructure**  
SQLite is sufficient for a single-tenant deployment. If multi-tenant or high-frequency scanning is needed, the `telemetry` table can be migrated to PostgreSQL with TimescaleDB for time-series efficiency — only `memory/db.py` changes.

---

## Signals collected

| Signal | Source | Storage |
|---|---|---|
| Agent wall-clock latency | `time.perf_counter()` in `agent_span` | `telemetry.duration_ms` |
| Per-agent prompt tokens | `response.usage` delta in `agent_span` | `telemetry.prompt_tokens` |
| Per-agent completion tokens | `response.usage` delta in `agent_span` | `telemetry.completion_tokens` |
| Agent error | Exception message caught in `agent_span` | `telemetry.error` |
| Pipeline quality score | `evaluate_pipeline()` result | `eval_history.overall_score` (existing) |
| Quality drift alert | 3-consecutive-scan drop detected in UI | Computed client-side from `quality_trend` |

---

## Consequences

**Positive:**
- Every scan now produces a complete per-agent timing breakdown with zero extra LLM calls
- Quality degradation is visible on the Dashboard before users notice bad output
- Error rate is tracked — a failing agent is visible without reading server logs
- Token usage per agent lays the groundwork for B-021 (Cost Per Run)

**Negative / trade-offs:**
- One additional SQLite write per agent per scan (~7 writes). At the scale this system operates, this is negligible.
- Spans before `save_scan()` have `scan_id = NULL` — they are still queryable by `workspace_id` but cannot be joined to the `scans` row. Acceptable for the current use case.
- Quality trend depends on `eval_history` being populated, which requires `workspace_id` to be set. Anonymous (no-workspace) scans have no quality trend.

---

## Relationship to other ADRs

- **ADR-001** (SQLite persistence) — telemetry extends the existing DB with one new table
- **ADR-005** (Memory architecture) — telemetry is observability infrastructure, not memory; it does not feed back into agent prompts
- **B-021** (Cost Per Run) — token tracking added here (`prompt_tokens`, `completion_tokens` per agent) is the foundation for USD cost computation in B-021
