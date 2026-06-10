"""
api/routers/workspace.py

GET    /api/workspace                          — list all saved workspaces
POST   /api/workspace                          — create / update a workspace
GET    /api/workspace/{workspace_id}/scans     — scan history for a workspace
GET    /api/workspace/{workspace_id}/scenarios — locked scenario registry
DELETE /api/workspace/{workspace_id}/scenarios — unlock registry (force new scan)
"""

from __future__ import annotations

from fastapi import APIRouter

import memory.db as db
from api.schemas import WorkspaceIn
from core.workspace import WorkspaceContext, list_workspaces, save_workspace_metadata

router = APIRouter()


def _ws_to_dict(ws: WorkspaceContext, workspace_id: int | None = None) -> dict:
    return {
        "customer": ws.customer,
        "project": ws.project,
        "function": ws.function,
        "business_tier": ws.business_tier,
        "user_type": ws.user_type,
        "business_context": ws.business_context,
        "customer_learning": ws.customer_learning,
        "workspace_id": workspace_id,
    }


@router.get("/api/workspace")
async def list_ws():
    """Return all saved workspaces with their DB ids."""
    results = []
    for ws in list_workspaces():
        try:
            ws_id = db.upsert_workspace(ws)
        except Exception:
            ws_id = None
        results.append(_ws_to_dict(ws, ws_id))
    return results


@router.post("/api/workspace")
async def upsert_ws(ws_in: WorkspaceIn):
    """Create or update a workspace. Returns the workspace with its id."""
    ws = WorkspaceContext(
        customer=ws_in.customer,
        project=ws_in.project,
        function=ws_in.function,
        business_tier=ws_in.business_tier,
        user_type=ws_in.user_type,
        business_context=ws_in.business_context,
        customer_learning=ws_in.customer_learning,
    )
    save_workspace_metadata(ws)
    workspace_id = db.upsert_workspace(ws)
    return _ws_to_dict(ws, workspace_id)


@router.get("/api/workspace/{workspace_id}/scans")
async def get_workspace_scans(workspace_id: int):
    """Return scan history rows (no full result JSON) for a workspace."""
    return db.get_all_scans(workspace_id)


@router.get("/api/workspace/{workspace_id}/scenarios")
async def get_workspace_scenarios(workspace_id: int):
    """Return locked scenarios for a workspace, without raw numpy embeddings."""
    rows = db.get_locked_scenarios(workspace_id)
    clean = []
    for row in rows:
        row.pop("embedding", None)         # numpy array — not serialisable
        row.pop("attack_chain_json", None)  # already parsed into attack_chain
        clean.append(row)
    return clean


@router.delete("/api/workspace/{workspace_id}/scenarios")
async def delete_workspace_scenarios(workspace_id: int):
    """Unlock the scenario registry — the next scan will generate fresh scenarios."""
    db.delete_scenarios(workspace_id)
    return {"deleted": True, "workspace_id": workspace_id}
