"""
api/routers/github.py

POST /api/github/scan     — fetch a public GitHub repo, extract README for
                            business context, then run the full FMEA pipeline.
                            Returns an SSE stream with per-stage progress events.

POST /api/github/preview  — return the repo file listing + README path without
                            running any AI analysis.  Used by the UI to let the
                            user confirm what will be scanned.
"""

from __future__ import annotations

import asyncio
import queue

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.schemas import WorkspaceIn, serialize_result
from api.sse import sse_event
from api.store import build_workspace, next_scan_id, scan_store
from core.github_fetcher import fetch_readme, fetch_selected_files, scan_repo
from core.workspace import WorkspaceContext
from workflows.fmea_pipeline import run_fmea

router = APIRouter()


# ── Request models ────────────────────────────────────────────────────────────

class GithubScanRequest(BaseModel):
    repo_url: str
    workspace: WorkspaceIn | None = None
    max_failure_modes: int = 7
    force_rerun: bool = False
    selected_files: list[str] | None = None


class GithubPreviewRequest(BaseModel):
    repo_url: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/github/scan")
async def github_scan(req: GithubScanRequest):
    """
    Full GitHub-repo FMEA scan delivered as an SSE stream.

    Stage sequence:
      repo_scan   — fetching the repository file tree
      repo_tree   — file list ready; emits file_count and readme path
      readme      — README fetched (used as business context)
      fetch_files — downloading code files
      files_ready — all code downloaded; pipeline starting
      surveyor / saboteur / controls / actuary / sre / validator / registry / eval
      complete    — full result + scan_id
      error       — something went wrong
    """

    async def generate():
        # ── Stage 1: scan the repo tree ───────────────────────────────────────
        yield sse_event({"stage": "repo_scan", "msg": "Scanning repository tree…"})

        try:
            ref, files, readme_path = await asyncio.to_thread(scan_repo, req.repo_url)
        except Exception as exc:
            yield sse_event({"stage": "error", "msg": str(exc)}, event="error")
            return

        if req.selected_files is not None:
            allowed = set(req.selected_files)
            files = [f for f in files if f in allowed]

        yield sse_event({
            "stage": "repo_tree",
            "msg": f"Found {len(files)} file(s) to analyse",
            "file_count": len(files),
            "readme": readme_path,
            "ref": {"owner": ref.owner, "repo": ref.repo, "branch": ref.branch},
        })

        # ── Stage 2: fetch README → business context ──────────────────────────
        readme_text = ""
        if readme_path:
            yield sse_event({
                "stage": "readme",
                "msg": f"Reading {readme_path} for business context…",
            })
            try:
                readme_text = await asyncio.to_thread(fetch_readme, ref, readme_path)
            except Exception:
                readme_text = ""  # non-fatal — proceed without context

        # Build workspace: auto-fill from repo if no explicit config provided
        ws_in = req.workspace
        ws = WorkspaceContext(
            customer=ws_in.customer   if ws_in else ref.owner,
            project=ws_in.project     if ws_in else ref.repo,
            function=ws_in.function   if ws_in else "",
            business_tier=ws_in.business_tier if ws_in else "Tier 1",
            user_type=ws_in.user_type if ws_in else "external_customers",
            # README always wins over any manually typed context
            business_context=readme_text[:2000] if readme_text else (
                ws_in.business_context if ws_in else ""
            ),
            customer_learning=ws_in.customer_learning if ws_in else True,
        )

        # ── Stage 3: download code files ─────────────────────────────────────
        yield sse_event({
            "stage": "fetch_files",
            "msg": f"Downloading {len(files)} file(s) from GitHub…",
        })

        try:
            code, fetched = await asyncio.to_thread(fetch_selected_files, ref, files)
        except Exception as exc:
            yield sse_event(
                {"stage": "error", "msg": f"File download failed: {exc}"},
                event="error",
            )
            return

        yield sse_event({
            "stage": "files_ready",
            "msg": f"Downloaded {len(fetched)} file(s) ({len(code):,} chars) — starting pipeline",
            "fetched_count": len(fetched),
            "code_length": len(code),
        })

        # ── Stage 4: FMEA pipeline ────────────────────────────────────────────
        progress: queue.SimpleQueue[str] = queue.SimpleQueue()

        def _on_progress(stage: str) -> None:
            progress.put(stage)

        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(
            None,
            lambda: run_fmea(
                code,
                max_failure_modes=req.max_failure_modes,
                force_rerun=req.force_rerun,
                workspace=ws,
                on_progress=_on_progress,
            ),
        )

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
            "code": code,
            "workspace": req.workspace,
        }

        yield sse_event({
            "stage": "complete",
            "scan_id": scan_id,
            "result": serialized,
            "repo": {
                "owner": ref.owner,
                "repo": ref.repo,
                "branch": ref.branch,
                "files_scanned": len(fetched),
                "readme_used": bool(readme_text),
            },
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/github/preview")
async def github_preview(req: GithubPreviewRequest):
    """
    Return the file listing for a public GitHub repo without running any analysis.
    Used by the UI to let the user confirm what will be scanned.
    """
    try:
        ref, files, readme_path = await asyncio.to_thread(scan_repo, req.repo_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "ref": {"owner": ref.owner, "repo": ref.repo, "branch": ref.branch},
        "file_count": len(files),
        "files": files,
        "readme_path": readme_path,
        "has_readme": readme_path is not None,
    }
