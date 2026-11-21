"""
api/routers/scoring.py — Expert score adjustment endpoints (B-001).

POST /api/scoring/adjustment    — persist a security-engineer RPN adjustment
GET  /api/scoring/adjustments/{workspace_id} — fetch audit trail for a workspace
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import memory.db as db
from core.priority import MIN_DOWNGRADE_JUSTIFICATION_CHARS, lowers_catastrophic_severity, priority_for

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


class AdjustmentIn(BaseModel):
    workspace_id:  int   = Field(..., gt=0)
    failure_mode:  str   = Field(..., min_length=1)
    new_s:         int   = Field(..., ge=1, le=10)
    new_o:         int   = Field(..., ge=1, le=10)
    new_d:         int   = Field(..., ge=1, le=10)
    justification: str   = Field(..., min_length=1)


class AdjustmentOut(BaseModel):
    id:           int
    workspace_id: int
    failure_mode: str
    new_s:        int
    new_o:        int
    new_d:        int
    new_rpn:      int
    justification: str
    created_at:   str
    source:       str = "manual"   # "manual" (Scoring page) or "chat" (B-025)
    adjusted_by:  str | None = None   # signed-in user (B-015); None for rows saved before sign-in existed
    priority:     str = ""
    flagged:      bool = False     # took a Severity >= 9 scenario below 9 (B-034)


@router.post("/adjustment", response_model=AdjustmentOut, status_code=201)
def create_adjustment(body: AdjustmentIn, request: Request):
    current = db.get_current_severity(body.workspace_id, body.failure_mode)
    flagged = current is not None and lowers_catastrophic_severity(current, body.new_s)
    if flagged and len(body.justification.strip()) < MIN_DOWNGRADE_JUSTIFICATION_CHARS:
        raise HTTPException(422, f"Lowering a Severity {current} scenario below 9 needs a justification "
                                 f"of at least {MIN_DOWNGRADE_JUSTIFICATION_CHARS} characters.")
    adj_id = db.save_adjustment(
        workspace_id=body.workspace_id,
        failure_mode=body.failure_mode,
        new_s=body.new_s,
        new_o=body.new_o,
        new_d=body.new_d,
        justification=body.justification,
        adjusted_by=request.state.user["username"],
    )
    return {
        "id":           adj_id,
        "workspace_id": body.workspace_id,
        "failure_mode": body.failure_mode,
        "new_s":        body.new_s,
        "new_o":        body.new_o,
        "new_d":        body.new_d,
        "new_rpn":      body.new_s * body.new_o * body.new_d,
        "justification": body.justification,
        "created_at":   datetime.now().isoformat(),
        "source":       "manual",
        "adjusted_by":  request.state.user["username"],
        "priority":     priority_for(body.new_s, body.new_o, body.new_d).band,
        "flagged":      flagged,
    }


@router.get("/adjustments/{workspace_id}", response_model=list[AdjustmentOut])
def list_adjustments(workspace_id: int):
    rows = db.get_adjustments(workspace_id)
    return [
        {**r, "workspace_id": workspace_id, "priority": priority_for(r["new_s"], r["new_o"], r["new_d"]).band}
        for r in rows
    ]
