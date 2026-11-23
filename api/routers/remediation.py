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

from agents.remediator import apply_and_rescan
from api.schemas import RemediateRequest
import memory.db as db
from core import auth, fix_proposal
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


# ── B-053, B-056 (ADR-033): a fix for one chosen action, from the stored scan, and the person's decision on it ──

class FixRequest(BaseModel):
    workspace_id: int
    scan_id: int                 # the saved scan (db_scan_id in every scan result), not the server's in-memory counter
    failure_mode: str
    action_id: str


class FixEdit(BaseModel):
    file: str
    start_line: int
    end_line: int
    replacement: str


class FixDecision(FixRequest):
    decision: Literal["accepted", "edited", "rejected"]
    edits: list[FixEdit] = []


def _stored_fix_target(req: FixRequest):
    """(failure, action, source files) from the stored snapshot, or a plain HTTP error."""
    snapshot = db.get_snapshot_for_scan(req.workspace_id, req.scan_id)
    if snapshot is None:
        raise HTTPException(404, "This scan is not stored for this project. Run the scan again to propose fixes.")
    result = snapshot["findings"]
    failures = result.get("failures", [])
    index = next((i for i, f in enumerate(failures) if f.get("failure_mode") == req.failure_mode), None)
    if index is None:
        raise HTTPException(404, "That finding is not part of the stored scan. Reload the page and try again.")
    plans = result.get("remediations", [])
    plan_row = next((p for p in plans if p.get("failure_mode") == req.failure_mode), None)
    if plan_row is None and len(plans) == len(failures):
        plan_row = plans[index]                      # plans stored before names were aligned pair with findings by position
    if plan_row is None:
        raise HTTPException(404, "That finding has no fix actions.")
    corrective, preventive = plan_actions(RemediationPlan(**plan_row))
    action = next((a for a in corrective + preventive if a.id == req.action_id), None)
    if action is None:
        raise HTTPException(404, "That action is not part of this finding.")
    files = db.get_snapshot_files(snapshot["id"])
    if not files:
        raise HTTPException(409, "The source code of this scan is no longer stored (source retention), so a fix cannot be written. "
                                 "Run the scan again, or keep source code for longer in the retention setting.")
    return FailureMode(**failures[index]), action, files


@router.post("/api/remediate/finding")
async def propose_fix(req: FixRequest):
    """A proposed fix (edits, diff, test) for one action of one finding. Nothing is applied anywhere."""
    failure, action, files = _stored_fix_target(req)
    loop = asyncio.get_running_loop()
    try:
        proposal = await loop.run_in_executor(None, lambda: fix_proposal.propose(failure, action, files))
    except fix_proposal.FixError as exc:
        raise HTTPException(502, str(exc)) from None
    except (Exception, ProviderBlocked) as exc:
        raise HTTPException(502, scan_error_event(exc)["msg"].replace("The scan failed.", "Proposing the fix failed.")) from None
    return {"failure_mode": req.failure_mode, "action_id": req.action_id, **proposal}


@router.post("/api/remediate/decision")
async def record_fix_decision(req: FixDecision, request: Request):
    """Record accepted, edited or rejected with the person's name; the diff is rebuilt from their final text."""
    failure, action, files = _stored_fix_target(req)
    shown, _ = fix_proposal.pick_context(failure, files)
    spans = {p: fix_proposal.view_spans(p, t, failure) for p, t in shown.items()}
    if req.decision != "rejected" and not req.edits:
        raise HTTPException(422, "An accepted or edited fix needs its edits.")
    try:
        final = fix_proposal.apply_final([e.model_dump() for e in req.edits], shown, spans) if req.edits else {"edits": [], "diff": "", "diff_sha256": fix_proposal.diff_hash(""), "parse_errors": []}
    except fix_proposal.FixError as exc:
        raise HTTPException(422, f"Those edits do not fit the stored files: {exc}") from None
    clean = lambda text: " ".join(str(text).replace("|", "/").split())[:160]          # model-written text: one line, no separators
    touched = ", ".join(sorted({clean(e["file"]) for e in final["edits"]})) or "none"
    auth.record_event(request.state.user, f"fix_{req.decision}",
                      f"{clean(req.failure_mode)} | action {clean(req.action_id)} | scan {req.scan_id} | files {touched} | diff sha256 {final['diff_sha256']}")
    return {"decision": req.decision, "failure_mode": req.failure_mode, "action_id": req.action_id, "diff": final["diff"],
            "diff_sha256": final["diff_sha256"], "parse_errors": final["parse_errors"]}
