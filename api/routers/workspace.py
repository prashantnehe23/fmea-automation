"""
api/routers/workspace.py

GET    /api/workspace                          — list all saved workspaces
POST   /api/workspace                          — create / update a workspace
GET    /api/workspace/{workspace_id}/scans     — scan history for a workspace
GET    /api/workspace/{workspace_id}/scenarios — locked scenario registry
DELETE /api/workspace/{workspace_id}/scenarios — unlock registry (force new scan)

GET    /api/portfolios                         — list all portfolios (nested projects)
POST   /api/portfolios                         — create portfolio
DELETE /api/portfolios/{portfolio_id}          — delete portfolio + its projects

POST   /api/portfolios/{portfolio_id}/projects — create project
PATCH  /api/projects/{project_id}              — update project fields
DELETE /api/projects/{project_id}              — delete project
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import memory.db as db
from api.schemas import PortfolioIn, ProjectIn, ProjectPatch, WorkspaceIn
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


@router.get("/api/projects/{project_id}/latest-scan")
async def project_latest_scan(project_id: int):
    """The project's latest stored scan, so every user of the install sees the same results (B-015)."""
    scan = db.get_project_scan(project_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="No scan stored for this project")
    return scan


@router.delete("/api/workspace/{workspace_id}/sources")
async def delete_stored_sources(workspace_id: int):
    """Delete the scanned source code stored for a project. Findings and scores are kept (B-042)."""
    if not db.workspace_exists(workspace_id):
        raise HTTPException(status_code=404, detail="Unknown project")
    return {"files_deleted": db.delete_sources_for_workspace(workspace_id)}


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


# ── Portfolio / Project hierarchy (B-007) ─────────────────────────────────────

@router.get("/api/portfolios")
async def list_portfolios():
    """Return all portfolios with nested projects."""
    return db.list_portfolios()


@router.post("/api/portfolios", status_code=201)
async def create_portfolio(body: PortfolioIn):
    """Create a portfolio. Returns {id, name, created_at, projects: []}."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Portfolio name must not be blank")
    created = db.create_portfolio(body.name.strip())
    return {**created, "projects": []}


@router.delete("/api/portfolios/{portfolio_id}")
async def delete_portfolio(portfolio_id: int):
    """Delete a portfolio and all its projects."""
    db.delete_portfolio(portfolio_id)
    return {"deleted": True, "portfolio_id": portfolio_id}


@router.post("/api/portfolios/{portfolio_id}/projects", status_code=201)
async def create_project(portfolio_id: int, body: ProjectIn):
    """Create a project under a portfolio."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Project name must not be blank")
    return db.create_project(
        portfolio_id=portfolio_id,
        name=body.name.strip(),
        repo_url=body.repo_url or None,
        business_tier=body.business_tier,
        user_type=body.user_type,
    )


@router.patch("/api/projects/{project_id}")
async def patch_project(project_id: int, body: ProjectPatch):
    """Partially update a project. Only provided fields are changed."""
    kwargs: dict = {}
    if "repo_url" in body.model_fields_set:
        kwargs["repo_url"] = body.repo_url
    if "business_tier" in body.model_fields_set:
        kwargs["business_tier"] = body.business_tier
    if "user_type" in body.model_fields_set:
        kwargs["user_type"] = body.user_type
    if kwargs:
        db.update_project(project_id, **kwargs)
    return {"updated": True, "id": project_id}


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    """Delete a single project."""
    db.delete_project(project_id)
    return {"deleted": True, "project_id": project_id}
