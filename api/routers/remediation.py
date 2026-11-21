"""
api/routers/remediation.py

POST /api/remediate             — run auto-remediation on a completed scan;
                                  returns SSE stream then a "complete" event.
GET  /api/remediate/{rem_id}    — retrieve completed remediation results.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agents.remediator import apply_and_rescan
from api.schemas import RemediateRequest
from api.sse import sse_event
from core.llm_errors import scan_error_event
from api.store import build_workspace, next_rem_id, remediation_store, scan_store
from core.models import FailureMode, RemediationPlan, RiskScore

router = APIRouter()


@router.post("/api/remediate")
async def submit_remediation(req: RemediateRequest):
    """
    Run auto-remediation against a previously completed scan.

    Event shapes:
      {"stage": "init",        "msg": "..."}
      {"stage": "remediating", "msg": "...", "count": N}
      {"stage": "complete",    "remediation_id": N, "results": [...]}
      {"stage": "error",       "msg": "..."}   (event: error)
    """
    if req.scan_id not in scan_store:
        raise HTTPException(
            status_code=404,
            detail="Scan not found — run a scan first",
        )

    stored = scan_store[req.scan_id]
    result = stored["result"]
    code   = stored["code"]
    ws_in  = stored["workspace"]

    async def generate():
        yield sse_event({"stage": "init", "msg": "Auto-remediation started"})

        try:
            failures = [FailureMode(**f) for f in result.get("failures", [])]
            risks    = [RiskScore(**r)   for r in result.get("risks", [])]
            plans    = [RemediationPlan(**p) for p in result.get("remediations", [])]
        except Exception as exc:
            yield sse_event(
                {"stage": "error", "msg": f"Failed to deserialise scan: {exc}"},
                event="error",
            )
            return

        yield sse_event({
            "stage": "remediating",
            "msg": f"Generating fixes for {len(failures)} failure mode(s)…",
            "count": len(failures),
        })

        ws = build_workspace(ws_in) if ws_in else None

        loop = asyncio.get_running_loop()
        fut  = loop.run_in_executor(
            None,
            lambda: apply_and_rescan(failures, plans, risks, code, ws),
        )

        while not fut.done():
            await asyncio.sleep(0.5)

        try:
            rem_results = fut.result()
        except Exception as exc:
            yield sse_event(scan_error_event(exc), event="error")
            return

        serialized = [r.model_dump() for r in rem_results]
        rem_id = next_rem_id()
        remediation_store[rem_id] = serialized

        yield sse_event({
            "stage": "complete",
            "remediation_id": rem_id,
            "results": serialized,
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/remediate/{remediation_id}")
async def get_remediation(remediation_id: int):
    """Retrieve completed remediation results by id."""
    if remediation_id not in remediation_store:
        raise HTTPException(status_code=404, detail="Remediation not found")
    return remediation_store[remediation_id]
