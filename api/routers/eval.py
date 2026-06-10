"""
api/routers/eval.py

GET /api/eval/history/{workspace_id} — last N eval history rows for a workspace.
"""

from fastapi import APIRouter

import memory.db as db

router = APIRouter()


@router.get("/api/eval/history/{workspace_id}")
async def get_eval_history(workspace_id: int, n: int = 20):
    """Return the last *n* eval history rows for a workspace (most recent first)."""
    rows = db.get_eval_history(workspace_id, n)
    # agent_scores_json is already parsed into agent_scores in db.py
    for row in rows:
        row.pop("agent_scores_json", None)
    return rows
