"""
api/routers/remediation.py

POST /api/remediate             — run auto-remediation on a completed scan;
                                  returns SSE stream then a "complete" event.
GET  /api/remediate/{rem_id}    — retrieve completed remediation results.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse

from agents.remediator import apply_and_rescan, generate_fix
from api.schemas import RemediateRequest
from core import auth
from core.actions import plan_actions
from api.sse import sse_event
from core.llm_errors import scan_error_event
from core.provider_block import ProviderBlocked
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
        except (Exception, ProviderBlocked) as exc:
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


# ── B-053: fix for one chosen action, and the person's decision on it ──────────────────────────────────────

class FixRequest(BaseModel):
    scan_id: int
    failure_mode: str
    action_id: str


class FixDecision(FixRequest):
    decision: Literal["accepted", "edited", "rejected"]


def _stored_failure_and_plan(req: FixRequest):
    stored = scan_store.get(req.scan_id)
    if stored is None:
        raise HTTPException(404, "This scan is no longer available on the server. Run the scan again to propose fixes.")
    result = stored["result"]
    failure = next((FailureMode(**f) for f in result.get("failures", []) if f.get("failure_mode") == req.failure_mode), None)
    plan = next((RemediationPlan(**p) for p in result.get("remediations", []) if p.get("failure_mode") == req.failure_mode), None)
    if failure is None or plan is None:
        raise HTTPException(404, "That finding is not part of this scan.")
    if not any(a.id == req.action_id for a in plan_actions(plan)[0] + plan_actions(plan)[1]):
        raise HTTPException(404, "That action is not part of this finding.")
    return stored, failure, plan


@router.post("/api/remediate/finding")
async def propose_fix(req: FixRequest):
    """A proposed fix (diff, replacement code, test) for one action of one finding. Nothing is applied."""
    stored, failure, plan = _stored_failure_and_plan(req)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: generate_fix(failure, plan, stored["code"], req.action_id))
    except (Exception, ProviderBlocked) as exc:
        raise HTTPException(502, scan_error_event(exc)["msg"].replace("The scan failed.", "Proposing the fix failed.")) from None
    return {"failure_mode": req.failure_mode, "action_id": req.action_id, "code_diff": result.code_diff, "test_code": result.test_code,
            "test_description": result.test_description, "patched_snippet": result.patched_snippet}


@router.post("/api/remediate/decision")
async def record_fix_decision(req: FixDecision, request: Request):
    """Record accepted, edited or rejected with the person's name. The code itself is not stored here."""
    _stored_failure_and_plan(req)
    clean = lambda text: " ".join(str(text).replace("|", "/").split())[:160]          # model-written text: one line, no separators
    auth.record_event(request.state.user, f"fix_{req.decision}", f"{clean(req.failure_mode)} | action {clean(req.action_id)} | scan {req.scan_id}")
    return {"decision": req.decision, "failure_mode": req.failure_mode, "action_id": req.action_id}
