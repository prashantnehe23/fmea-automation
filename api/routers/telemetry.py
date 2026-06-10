"""
api/routers/telemetry.py

GET /api/telemetry/{workspace_id}  — aggregated observability data for a workspace.

Returns:
  last_scan_latency:  {agent: duration_ms} for the most recent scan
  agent_avg_ms:       {agent: avg_duration_ms} across last 20 scans
  error_rate:         fraction of agent spans that errored (0.0–1.0)
  quality_trend:      [{timestamp, score, passed}] from eval_history (oldest→newest)
  total_spans:        total telemetry spans recorded for this workspace
"""

from fastapi import APIRouter
import memory.db as _db

router = APIRouter()


@router.get("/api/telemetry/{workspace_id}")
async def get_telemetry(workspace_id: int, n: int = 20):
    """Return aggregated observability metrics for a workspace."""
    return _db.get_telemetry_summary(workspace_id, n_scans=n)
