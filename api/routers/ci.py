"""
api/routers/ci.py — B-012 (ADR-029): the pull-request check, its per-project settings and the API tokens
that CI uses to call it.

POST /api/pr-check                    — scan a pull request's head and return a verdict (token or session)
GET|PUT /api/projects/{id}/pr-check   — per-project settings (enabled, failure severity, USD budget)
GET|POST /api/tokens, DELETE /api/tokens/{id} — API tokens for CI (administrators)
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import memory.db as db
from core import auth
from core.pr_check import PrCheckError, run_pr_check

router = APIRouter(tags=["ci"])


class PrCheckRequest(BaseModel):
    repo: str = Field(..., pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")          # owner/name
    head_sha: str = Field(..., pattern=r"^[A-Za-z0-9._-]{4,100}$")
    pr_number: int | None = Field(None, gt=0)
    budget_usd: float | None = Field(None, gt=0, le=50)


class PrCheckConfig(BaseModel):
    enabled: bool | None = None
    fail_severity: int | None = Field(None, ge=1, le=10)
    budget_usd: float | None = Field(None, gt=0, le=50)


class TokenIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    repo: str | None = Field(None, pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")    # limit the token to one repository


@router.post("/api/pr-check")
async def pr_check(body: PrCheckRequest, request: Request):
    owner, repo = body.repo.split("/", 1)
    scope = request.state.user.get("scope_repo")
    if scope and scope != body.repo.lower():
        raise HTTPException(403, f"This token is limited to {scope}.")
    try:
        out = await asyncio.to_thread(run_pr_check, owner, repo, body.head_sha, body.pr_number, body.budget_usd)
    except PrCheckError as exc:
        raise HTTPException(exc.status, str(exc))
    number = f"#{body.pr_number}" if body.pr_number else ""
    auth.record_event(request.state.user, "pr_check", f"{body.repo}{number} {out['verdict']} ${out['cost_usd']:.2f}")
    return out


@router.get("/api/projects/{project_id}/pr-check")
def get_config(project_id: int):
    if not db.project_exists(project_id):
        raise HTTPException(404, "Unknown project")
    return db.get_pr_check_config(project_id)


@router.put("/api/projects/{project_id}/pr-check")
def put_config(project_id: int, body: PrCheckConfig):
    if not db.project_exists(project_id):
        raise HTTPException(404, "Unknown project")
    return db.set_pr_check_config(project_id, enabled=body.enabled, fail_severity=body.fail_severity,
                                  budget_usd=body.budget_usd)


@router.get("/api/tokens")
def list_tokens():
    return auth.list_api_tokens()


@router.post("/api/tokens", status_code=201)
def create_token(body: TokenIn, request: Request):
    created = auth.create_api_token(body.name.strip(), request.state.user["username"], body.repo)
    auth.record_event(request.state.user, "token_created", body.name.strip() + (f" for {body.repo}" if body.repo else ""))
    return created                      # the token is shown this once and never again


@router.delete("/api/tokens/{token_id}")
def revoke_token(token_id: int, request: Request):
    if not auth.revoke_api_token(token_id):
        raise HTTPException(404, "Unknown token")
    auth.record_event(request.state.user, "token_revoked", str(token_id))
    return {"revoked": True}
