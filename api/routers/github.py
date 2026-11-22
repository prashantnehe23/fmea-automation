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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.schemas import WorkspaceIn, serialize_result
from api.sse import sse_event
from core.llm_errors import scan_error_event
from core.provider_block import ProviderBlocked
from api.store import build_workspace, next_scan_id, scan_store
from core import auth, repo_credentials
from core.chat import persist_scan_for_chat
from core.untrusted import sanitize_text
from core.github_fetcher import RepoAccessError, fetch_contents, fetch_readme, list_repo, scan_repo
from core.estimate import estimate_scan
from core.scan_scope import DEFAULT_MAX_BATCHES, MAX_BYTES, build_scan_input, plan_batches, summarise_manifest
from core.workspace import WorkspaceContext
from workflows.fmea_pipeline import run_fmea

router = APIRouter()


def _repo_error_event(exc: Exception, prefix: str = "") -> dict:
    """SSE error payload: a plain message (with a Settings action) for access problems, else the text as before."""
    if isinstance(exc, RepoAccessError):
        return {"stage": "error", "msg": exc.message, "code": exc.code, "action": "open_settings"}
    return {"stage": "error", "msg": prefix + str(exc)}


# ── Request models ────────────────────────────────────────────────────────────

class GithubScanRequest(BaseModel):
    repo_url: str
    workspace: WorkspaceIn | None = None
    max_failure_modes: int | None = None     # None = no cap on what is reported (B-028 phase 0)
    max_batches: int = Field(DEFAULT_MAX_BATCHES, ge=1, le=10)   # passes over a large repository (cost ceiling)
    force_rerun: bool = False
    selected_files: list[str] | None = None


class GithubPreviewRequest(BaseModel):
    repo_url: str
    max_batches: int = Field(DEFAULT_MAX_BATCHES, ge=1, le=10)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/github/scan")
async def github_scan(req: GithubScanRequest, request: Request):
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
            ref, entries, readme_path = await asyncio.to_thread(list_repo, req.repo_url)
        except Exception as exc:
            yield sse_event(_repo_error_event(exc), event="error")
            return

        if repo_credentials.token_for(ref.owner):     # whoever scans can read what the stored token reaches
            auth.record_event(getattr(request.state, "user", None), "scan_with_stored_token", f"{ref.owner}/{ref.repo}")

        files = sorted(e.path for e in entries if e.included)
        not_selected: set[str] = set()
        if req.selected_files is not None:
            allowed = set(req.selected_files)
            not_selected = {f for f in files if f not in allowed}
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
            business_context=sanitize_text(readme_text, 2000) if readme_text else (
                sanitize_text(ws_in.business_context, 2000) if ws_in else ""
            ),
            customer_learning=ws_in.customer_learning if ws_in else True,
        )

        # ── Stage 3: download code files ─────────────────────────────────────
        yield sse_event({
            "stage": "fetch_files",
            "msg": f"Downloading {len(files)} file(s) from GitHub…",
        })

        try:
            # Plan the batches by priority from the tree's sizes, download only those files, and record
            # everything else as not examined (B-033): never a silent cut.
            wanted = set(files)
            planned, _ = plan_batches([e for e in entries if e.path in wanted], MAX_BYTES, req.max_batches)
            chosen = [e for b in planned for e in b]
            contents, _errors = await asyncio.to_thread(fetch_contents, ref, [e.path for e in chosen])
        except Exception as exc:
            yield sse_event(_repo_error_event(exc, "File download failed: "), event="error")
            return
        scan_input = build_scan_input(contents, entries, not_selected=not_selected, max_batches=req.max_batches)
        code, fetched = scan_input.code, scan_input.examined
        scope = {"manifest": scan_input.manifest, "summary": summarise_manifest(scan_input.manifest),
                 "secrets": scan_input.secret_findings}

        yield sse_event({
            "stage": "files_ready",
            "msg": (f"Downloaded {len(fetched)} file(s) ({len(code):,} chars); "
                    f"{scope['summary']['not_examined']} not examined — starting pipeline"),
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
                scope=scope,
                batches=scan_input.batch_codes,
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
        except (Exception, ProviderBlocked) as exc:
            yield sse_event(scan_error_event(exc), event="error")
            return

        scan_id = next_scan_id()
        serialized = serialize_result(result)
        scan_store[scan_id] = {
            "result": serialized,
            "code": code,
            "workspace": req.workspace,
        }
        persist_scan_for_chat(serialized, code, known_paths=fetched)  # B-025: results chat memory

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
    Return the file listing for a GitHub repo (private ones use the owner's stored token) without running any analysis.
    Used by the UI to let the user confirm what will be scanned.
    """
    try:
        ref, entries, readme_path = await asyncio.to_thread(list_repo, req.repo_url)
    except RepoAccessError as exc:
        raise HTTPException(status_code=400, detail=exc.message)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    files = sorted(e.path for e in entries if e.included)
    planned, over = plan_batches([e for e in entries if e.included], MAX_BYTES, req.max_batches)
    estimate = estimate_scan([sum(e.size or 0 for e in b) for b in planned])
    estimate.update(files_examined=sum(len(b) for b in planned), files_unexamined=len(over))
    return {
        "ref": {"owner": ref.owner, "repo": ref.repo, "branch": ref.branch},
        "estimate": estimate,
        "file_count": len(files),
        "files": files,
        "readme_path": readme_path,
        "has_readme": readme_path is not None,
    }
