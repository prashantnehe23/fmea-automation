"""
api/routers/imports.py — B-045 (ADR-028): SARIF import and export.

POST /api/import/sarif?workspace_id=N   — body is the SARIF file; findings wait for the project's next scan
GET  /api/projects/{id}/sarif           — the project's latest scan as SARIF 2.1.0
"""

import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import memory.db as db
from core import auth
from core.sarif import MAX_BYTES, MAX_RESULTS, SarifError, export_sarif, parse_sarif

router = APIRouter(tags=["import"])


@router.post("/api/import/sarif")
async def import_sarif(request: Request, workspace_id: int):
    if not db.workspace_exists(workspace_id):
        raise HTTPException(status_code=404, detail="Unknown project")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 10 MB.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(status_code=413, detail="The file is larger than 10 MB.")
        chunks.append(chunk)
    body = b"".join(chunks)
    snap = db.get_latest_snapshot(workspace_id)
    files = db.get_snapshot_files(snap["id"]) if snap else {}
    try:
        parsed = parse_sarif(body, files)
    except SarifError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    import_id = uuid.uuid4().hex[:12]
    added, duplicates = db.add_imported_findings(
        workspace_id, import_id, ", ".join(parsed.tools)[:200],
        [(i.dedupe_key, i.failure.model_dump()) for i in parsed.items])
    auth.record_event(request.state.user, "sarif_import", f"{import_id}: {', '.join(parsed.tools)}; {added} new")
    return {
        "import_id": import_id, "tools": parsed.tools, "read": parsed.read, "added": added, "duplicates": duplicates,
        "skipped": [{"reason": r, "count": n} for r, n in parsed.skipped.items()],
        "truncated": parsed.truncated, "limit": MAX_RESULTS,
        "pending_total": len(db.pending_imported_findings(workspace_id)),
        "note": "Imported findings are scored by the next scan of this project.",
    }


@router.get("/api/projects/{project_id}/sarif")
async def project_sarif(project_id: int):
    workspace_id = db.workspace_id_for_project(project_id)
    snap = db.get_latest_snapshot(workspace_id) if workspace_id else None
    if snap is None:
        raise HTTPException(status_code=404, detail="No scan stored for this project")
    states = {r["failure_mode"]: r["state"] for r in db.get_locked_scenarios(workspace_id)}
    return JSONResponse(export_sarif(snap["findings"], states), media_type="application/sarif+json",
                        headers={"Content-Disposition": 'attachment; filename="fmea-results.sarif"'})
