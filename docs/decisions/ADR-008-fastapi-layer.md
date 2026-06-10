# ADR-008: API Layer — FastAPI over Direct Python Import / GraphQL / gRPC

**Status:** Accepted  
**Date:** 2026-05-28  
**Deciders:** Platform team

---

## Context

The React frontend (ADR-007) currently reads from static mock data in `frontend/src/data.js`.
To deliver real value, it must drive the actual Python pipeline — submitting code for analysis,
retrieving scan results, triggering remediation, reading eval history, and managing workspace
configuration.

Three integration patterns were evaluated.

---

## Options Considered

| Option | Coupling | Streaming | Type safety | Ops overhead |
|---|---|---|---|---|
| **FastAPI (chosen)** | Loose (HTTP) | SSE / WebSocket | Pydantic → OpenAPI → TS types | Single process, `pip install fastapi uvicorn` |
| Direct Python import (no API) | Tight (same process) | No | N/A | None — but frontend must be Python-hosted |
| GraphQL (Strawberry / Ariadne) | Loose | Subscriptions | Schema → TS codegen | Extra layer; queries complex for this data model |
| gRPC | Loose | Streaming native | Proto → stubs | Protobuf compilation; poor browser support without gRPC-Web proxy |

---

## Decision

**FastAPI** with **Uvicorn** as the API layer between the React frontend and the Python
pipeline.

### Rationale

1. **Pydantic is already the type system.** `FailureMode`, `RiskScore`, `RemediationResult`,
   `WorkspaceContext` are all Pydantic models. FastAPI serialises them to JSON with zero
   additional mapping. The OpenAPI schema is generated automatically, enabling TypeScript
   client generation for the frontend.

2. **Streaming pipeline progress via SSE.** FMEA analysis takes 15-60 seconds (LLM calls).
   The frontend needs live progress updates (saboteur → actuary → validator → registry →
   eval). FastAPI's `StreamingResponse` with Server-Sent Events delivers this without
   WebSocket complexity.

3. **Single extra dependency.** `pip install fastapi uvicorn[standard]` — no new build tooling,
   no protocol buffer compiler, no schema registry. The existing `requirements.txt` gains two
   lines.

4. **CORS + dev proxy.** Vite's `server.proxy` config routes `/api/*` to `localhost:8000`
   during development, eliminating CORS issues without a separate reverse proxy.

5. **Standard deployment unit.** `uvicorn api.main:app` behind Nginx is the canonical Python
   web service pattern. Docker: one image running FastAPI + React static build, or two
   containers behind a simple compose file.

6. **Fits the existing module boundary.** `workflows/fmea_pipeline.py` exports `run_fmea()`.
   The API layer calls it; it does not reach into agent internals. The boundary is already
   correct.

### Planned API surface (v1)

```
POST   /api/scan                  # submit code + workspace config → scan_id (SSE stream)
GET    /api/scan/{scan_id}        # retrieve full result JSON
GET    /api/workspace/{id}/scans  # scan history list
GET    /api/workspace/{id}/scenarios  # locked scenario registry
DELETE /api/workspace/{id}/scenarios  # unlock registry (clear + force rerun)
POST   /api/remediate             # trigger apply_and_rescan → SSE stream
GET    /api/remediate/{scan_id}   # retrieve remediation results
GET    /api/workspace             # list workspaces
POST   /api/workspace             # upsert workspace config
GET    /api/eval/history/{ws_id}  # eval history for dashboard
```

### File layout

```
api/
  main.py        # FastAPI app, CORS, router mount
  routers/
    scan.py
    workspace.py
    remediation.py
    eval.py
  schemas.py     # request/response Pydantic models (thin wrappers over core/models.py)
  sse.py         # SSE event helpers
```

### Frontend wiring

Replace `frontend/src/data.js` static constants with:

```js
// frontend/src/api.js
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
export const fetchScans = (wsId) => fetch(`${BASE}/api/workspace/${wsId}/scans`).then(r => r.json());
// … one function per endpoint
```

Vite dev proxy (`vite.config.js`):
```js
server: { proxy: { '/api': 'http://localhost:8000' } }
```

---

## Consequences

- **Positive:** React frontend becomes fully functional; all demo data replaced by live
  pipeline results.
- **Positive:** OpenAPI schema auto-generated at `/docs` — frontend developers and API
  consumers have a self-documenting interface.
- **Positive:** Pipeline runs are decoupled from the UI — multiple clients (React, Streamlit,
  CI scripts, Slack bots) can call the same API.
- **Positive:** SSE enables live progress bars in the React scan UI with no polling.
- **Negative:** Two processes in development (`npm run dev` + `uvicorn api.main:app`). Mitigated
  by a `Makefile` `dev` target.
- **Negative:** Authentication is out of scope for v1 (local tool). When deploying to a shared
  or cloud server, add an auth layer (OAuth2 + JWT, or API key header) before the API is
  network-accessible.
- **Dependency:** Requires ADR-007 (React frontend) to be meaningful. Requires `memory/db.py`
  (ADR-001) to be the source of truth for scan history.

---

## Superseded by

Nothing. Active.
