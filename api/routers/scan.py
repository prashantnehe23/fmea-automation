"""
api/routers/scan.py

POST /api/scan    — submit code for FMEA analysis; returns SSE stream of
                    stage progress events, then a final "complete" event with
                    the full serialised result.
GET  /api/scan/{scan_id} — retrieve a completed scan result by session-local id.
"""

from __future__ import annotations

import asyncio
import queue

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.schemas import ScanRequest, serialize_result
from api.sse import sse_event
from api.store import build_workspace, next_scan_id, scan_store
from workflows.fmea_pipeline import run_fmea

router = APIRouter()


@router.post("/api/scan")
async def submit_scan(req: ScanRequest):
    """
    Start an FMEA scan on pasted code and stream progress via Server-Sent Events.

    Event shapes:
      {"stage": "init",       "msg": "..."}
      {"stage": "surveyor",   "status": "running"}  … etc
      {"stage": "complete",   "scan_id": N, "result": {...}}
      {"stage": "error",      "msg": "..."}   (event: error)
    """

    async def generate():
        progress: queue.SimpleQueue[str] = queue.SimpleQueue()

        def _on_progress(stage: str) -> None:
            progress.put(stage)

        ws = build_workspace(req.workspace) if req.workspace else None

        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(
            None,
            lambda: run_fmea(
                req.code,
                max_failure_modes=req.max_failure_modes,
                force_rerun=req.force_rerun,
                workspace=ws,
                on_progress=_on_progress,
            ),
        )

        yield sse_event({"stage": "init", "msg": "FMEA pipeline started"})

        while not fut.done():
            while not progress.empty():
                yield sse_event({"stage": progress.get_nowait(), "status": "running"})
            await asyncio.sleep(0.2)

        while not progress.empty():
            yield sse_event({"stage": progress.get_nowait(), "status": "done"})

        try:
            result = fut.result()
        except Exception as exc:
            yield sse_event({"stage": "error", "msg": str(exc)}, event="error")
            return

        scan_id = next_scan_id()
        serialized = serialize_result(result)
        scan_store[scan_id] = {
            "result": serialized,
            "code": req.code,
            "workspace": req.workspace,
        }

        yield sse_event({"stage": "complete", "scan_id": scan_id, "result": serialized})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/scan/{scan_id}")
async def get_scan(scan_id: int):
    """Retrieve a completed scan result by its session-local id."""
    if scan_id not in scan_store:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan_store[scan_id]["result"]
