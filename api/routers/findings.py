"""
api/routers/findings.py — B-031 (ADR-019): finding lifecycle.

GET  /api/workspace/{id}/findings        — every finding of a project with its state, plus the state history
POST /api/workspace/{id}/findings/state  — a person confirms a fix, accepts a risk or reopens a finding
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import memory.db as db
from core.findings import MANUAL_TARGETS, STATES

router = APIRouter(tags=["findings"])


class StateChange(BaseModel):
    failure_mode: str
    state: str


@router.get("/api/workspace/{workspace_id}/findings")
def list_findings(workspace_id: int):
    if not db.workspace_exists(workspace_id):
        raise HTTPException(404, "Unknown project")
    rows = db.get_locked_scenarios(workspace_id)
    return {
        "findings": [
            {"failure_mode": r["failure_mode"], "state": r["state"], "severity": r["severity"],
             "occurrence": r["occurrence"], "detection": r["detection"], "rpn": r["rpn"],
             "state_changed_at": r["state_changed_at"], "state_scan_id": r["state_scan_id"]}
            for r in rows
        ],
        "events": db.list_finding_events(workspace_id),
    }


@router.post("/api/workspace/{workspace_id}/findings/state")
def change_state(workspace_id: int, body: StateChange, request: Request):
    if body.state not in STATES or body.state not in MANUAL_TARGETS:
        raise HTTPException(422, f"A person can set: {', '.join(sorted(MANUAL_TARGETS))}.")
    if not db.workspace_exists(workspace_id):
        raise HTTPException(404, "Unknown project")
    current = next((r for r in db.get_locked_scenarios(workspace_id) if r["failure_mode"] == body.failure_mode), None)
    if current is None:
        raise HTTPException(404, "Unknown finding")
    if current["state"] == body.state:
        raise HTTPException(409, f"The finding is already {body.state}.")
    db.set_scenario_state(workspace_id, body.failure_mode, body.state, actor=request.state.user["username"],
                          note="set by a person")
    return {"failure_mode": body.failure_mode, "state": body.state}
