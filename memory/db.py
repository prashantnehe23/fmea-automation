"""
memory/db.py — SQLite persistence layer for FMEA scan results.

Database file: memory/fmea.db (next to this module).

Tables:
  workspaces    — customer/project identity
  scans         — full pipeline result JSON, one row per run
  scenarios     — locked failure mode registry with embeddings for semantic dedup
  eval_history  — pipeline eval scores per scan

Design notes:
  - sqlite3 is in Python stdlib; zero extra dependencies.
  - WAL journal mode: allows concurrent readers alongside one writer.
  - Embeddings stored as BLOB (numpy float32 bytes) for cosine similarity in Python.
  - For cloud/multi-tenant scale, migrate to PostgreSQL + pgvector: only this file changes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

_DB_PATH = Path(__file__).resolve().parent / "fmea.db"
_lock = threading.Lock()

# ── Schema ─────────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS workspaces (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    customer          TEXT    NOT NULL,
    project           TEXT    NOT NULL,
    function          TEXT,
    business_tier     TEXT,
    user_type         TEXT,
    business_context  TEXT,
    customer_learning INTEGER DEFAULT 1,
    created_at        TEXT    NOT NULL,
    UNIQUE(customer, project)
);

CREATE TABLE IF NOT EXISTS scans (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id            INTEGER REFERENCES workspaces(id),
    fingerprint             TEXT    NOT NULL,
    timestamp               TEXT    NOT NULL,
    result_json             TEXT    NOT NULL,
    remediation_results_json TEXT,
    llm_calls               INTEGER,
    cost_usd                REAL
);

CREATE TABLE IF NOT EXISTS scenarios (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id      INTEGER NOT NULL REFERENCES workspaces(id),
    first_fingerprint TEXT    NOT NULL,
    failure_mode      TEXT    NOT NULL,
    attack_chain_json TEXT,
    severity          INTEGER,
    occurrence        INTEGER,
    detection         INTEGER,
    rpn               INTEGER,
    embedding         BLOB,
    created_at        TEXT    NOT NULL,
    UNIQUE(workspace_id, failure_mode)
);

CREATE TABLE IF NOT EXISTS eval_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id      INTEGER REFERENCES workspaces(id),
    scan_id           INTEGER REFERENCES scans(id),
    timestamp         TEXT    NOT NULL,
    overall_passed    INTEGER,
    overall_score     REAL,
    agent_scores_json TEXT,
    llm_calls         INTEGER
);

CREATE TABLE IF NOT EXISTS telemetry (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT,
    scan_id           INTEGER,
    workspace_id      INTEGER,
    agent             TEXT    NOT NULL,
    duration_ms       REAL    DEFAULT 0,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    error             TEXT,
    ts                TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS adjustments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  INTEGER NOT NULL REFERENCES workspaces(id),
    failure_mode  TEXT    NOT NULL,
    new_s         INTEGER NOT NULL,
    new_o         INTEGER NOT NULL,
    new_d         INTEGER NOT NULL,
    new_rpn       INTEGER NOT NULL,
    justification TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id   INTEGER NOT NULL REFERENCES portfolios(id),
    name           TEXT    NOT NULL,
    repo_url       TEXT,
    business_tier  TEXT    NOT NULL DEFAULT 'Tier 1',
    user_type      TEXT    NOT NULL DEFAULT 'external_customers',
    created_at     TEXT    NOT NULL
);
"""


# ── Connection ─────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """Open (or create) fmea.db with WAL mode and create schema if needed."""
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    # Idempotent column migrations for existing telemetry rows
    for _col_sql in (
        "ALTER TABLE telemetry ADD COLUMN run_id TEXT",
        "ALTER TABLE telemetry ADD COLUMN cost_usd REAL DEFAULT 0",
        "ALTER TABLE scenarios ADD COLUMN embed_model TEXT",
    ):
        try:
            conn.execute(_col_sql)
            conn.commit()
        except Exception:
            pass  # column already exists
    conn.commit()
    return conn


# ── Workspaces ─────────────────────────────────────────────────────────────────

def upsert_workspace(ws) -> int:
    """
    Insert workspace if not present (keyed on customer+project).
    Returns workspace_id (int).
    """
    with _lock:
        conn = get_db()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO workspaces
                    (customer, project, function, business_tier, user_type,
                     business_context, customer_learning, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ws.customer,
                    ws.project,
                    getattr(ws, "function", None),
                    getattr(ws, "business_tier", None),
                    getattr(ws, "user_type", None),
                    getattr(ws, "business_context", None),
                    int(getattr(ws, "customer_learning", True)),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM workspaces WHERE customer=? AND project=?",
                (ws.customer, ws.project),
            ).fetchone()
            return row["id"]
        finally:
            conn.close()


# ── Scans ──────────────────────────────────────────────────────────────────────

def save_scan(
    workspace_id: int,
    fingerprint: str,
    result_json: str,
    llm_calls: int = 0,
    cost_usd: float = 0.0,
) -> int:
    """Insert a scan row. Returns scan_id."""
    with _lock:
        conn = get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO scans
                    (workspace_id, fingerprint, timestamp, result_json, llm_calls, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (workspace_id, fingerprint, datetime.now().isoformat(),
                 result_json, llm_calls, cost_usd),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        finally:
            conn.close()


def update_scan_remediation(scan_id: int, remediation_json: str) -> None:
    """Attach remediation results to an existing scan row."""
    with _lock:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE scans SET remediation_results_json=? WHERE id=?",
                (remediation_json, scan_id),
            )
            conn.commit()
        finally:
            conn.close()


def get_latest_scan(workspace_id: int, fingerprint: str) -> dict | None:
    """Return the most recent result_json dict for this workspace+fingerprint, or None."""
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT result_json FROM scans
            WHERE workspace_id=? AND fingerprint=?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (workspace_id, fingerprint),
        ).fetchone()
        if row:
            return json.loads(row["result_json"])
        return None
    finally:
        conn.close()


def get_all_scans(workspace_id: int) -> list[dict]:
    """Return summary rows for the scan history table (no result_json)."""
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, fingerprint, timestamp, llm_calls, cost_usd
            FROM scans WHERE workspace_id=?
            ORDER BY timestamp DESC
            """,
            (workspace_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Scenarios (registry) ───────────────────────────────────────────────────────

def upsert_scenario(
    workspace_id: int,
    fingerprint: str,
    failure_mode: str,
    attack_chain: list[str],
    severity: int,
    occurrence: int,
    detection: int,
    rpn: int,
    embedding: bytes,
    embed_model: str = "",
) -> None:
    """
    Insert scenario if not present (keyed on workspace_id + failure_mode).
    Does NOT update on conflict — the first scan's scores are the canonical ones.
    """
    with _lock:
        conn = get_db()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO scenarios
                    (workspace_id, first_fingerprint, failure_mode, attack_chain_json,
                     severity, occurrence, detection, rpn, embedding, embed_model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    fingerprint,
                    failure_mode,
                    json.dumps(attack_chain),
                    severity,
                    occurrence,
                    detection,
                    rpn,
                    embedding,
                    embed_model,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_locked_scenarios(workspace_id: int) -> list[dict]:
    """
    Return all locked scenario rows for this workspace.
    Each dict has: failure_mode, severity, occurrence, detection, rpn, embedding (bytes).
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT failure_mode, attack_chain_json, severity, occurrence, detection, rpn, embedding, embed_model
            FROM scenarios WHERE workspace_id=?
            ORDER BY rpn DESC
            """,
            (workspace_id,),
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            # Deserialise numpy array from BLOB
            if item["embedding"]:
                item["embedding"] = np.frombuffer(item["embedding"], dtype=np.float32)
                # Rows stored before B-022 were all made by OpenAI's model
                item["embed_model"] = item["embed_model"] or "text-embedding-3-small"
            else:
                item["embedding"] = None
            if item.get("attack_chain_json"):
                item["attack_chain"] = json.loads(item["attack_chain_json"])
            else:
                item["attack_chain"] = []
            result.append(item)
        return result
    finally:
        conn.close()


def update_scenario_embedding(
    workspace_id: int, failure_mode: str, embedding: bytes, embed_model: str
) -> None:
    """Replace a locked scenario's embedding (scores stay untouched)."""
    with _lock:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE scenarios SET embedding=?, embed_model=? WHERE workspace_id=? AND failure_mode=?",
                (embedding, embed_model, workspace_id, failure_mode),
            )
            conn.commit()
        finally:
            conn.close()


def delete_scenarios(workspace_id: int) -> None:
    """Wipe all locked scenarios for this workspace (user-triggered unlock)."""
    with _lock:
        conn = get_db()
        try:
            conn.execute("DELETE FROM scenarios WHERE workspace_id=?", (workspace_id,))
            conn.commit()
        finally:
            conn.close()


def scenario_count(workspace_id: int) -> int:
    """Return number of locked scenarios for this workspace."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM scenarios WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


# ── Eval history ───────────────────────────────────────────────────────────────

def save_eval(
    workspace_id: int | None,
    scan_id: int | None,
    eval_dict: dict[str, Any],
) -> None:
    """Persist a pipeline eval result."""
    agent_scores = {
        k: v for k, v in eval_dict.items()
        if isinstance(v, (int, float)) and k not in ("overall_score", "llm_calls")
    }
    with _lock:
        conn = get_db()
        try:
            conn.execute(
                """
                INSERT INTO eval_history
                    (workspace_id, scan_id, timestamp, overall_passed,
                     overall_score, agent_scores_json, llm_calls)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    scan_id,
                    datetime.now().isoformat(),
                    int(eval_dict.get("overall_passed", False)),
                    eval_dict.get("overall_score", 0.0),
                    json.dumps(agent_scores),
                    eval_dict.get("llm_calls", 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_eval_history(workspace_id: int, n: int = 20) -> list[dict]:
    """Return last N eval history rows for this workspace."""
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, scan_id, timestamp, overall_passed, overall_score,
                   agent_scores_json, llm_calls
            FROM eval_history WHERE workspace_id=?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (workspace_id, n),
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            if item.get("agent_scores_json"):
                item["agent_scores"] = json.loads(item["agent_scores_json"])
            else:
                item["agent_scores"] = {}
            result.append(item)
        return result
    finally:
        conn.close()


# ── Telemetry ──────────────────────────────────────────────────────────────────

def save_telemetry_span(
    run_id: str | None,
    scan_id: int | None,
    workspace_id: int | None,
    agent: str,
    duration_ms: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    error: str | None = None,
    cost_usd: float = 0.0,
) -> None:
    """Record one agent execution span. Non-blocking best-effort — silently ignored on failure."""
    with _lock:
        conn = get_db()
        try:
            conn.execute(
                """
                INSERT INTO telemetry
                    (run_id, scan_id, workspace_id, agent, duration_ms,
                     prompt_tokens, completion_tokens, error, cost_usd, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, scan_id, workspace_id, agent, duration_ms,
                 prompt_tokens, completion_tokens, error, cost_usd,
                 datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()


# ── Score adjustments (L2 memory) ─────────────────────────────────────────────

def save_adjustment(
    workspace_id: int,
    failure_mode: str,
    new_s: int,
    new_o: int,
    new_d: int,
    justification: str,
) -> int:
    """Persist a security-engineer score adjustment. Returns adjustment id."""
    new_rpn = new_s * new_o * new_d
    with _lock:
        conn = get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO adjustments
                    (workspace_id, failure_mode, new_s, new_o, new_d, new_rpn, justification, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (workspace_id, failure_mode, new_s, new_o, new_d, new_rpn,
                 justification, datetime.now().isoformat()),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        finally:
            conn.close()


def get_adjustments(workspace_id: int) -> list[dict]:
    """Return all score adjustments for this workspace, most recent first."""
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, failure_mode, new_s, new_o, new_d, new_rpn, justification, created_at
            FROM adjustments WHERE workspace_id=?
            ORDER BY created_at DESC
            """,
            (workspace_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Portfolio / Project hierarchy (B-007) ─────────────────────────────────────

_UNSET = object()  # sentinel for "field not provided" in update_project


def create_portfolio(name: str) -> dict:
    """Insert a portfolio row. Returns {id, name, created_at}."""
    with _lock:
        conn = get_db()
        try:
            ts = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO portfolios (name, created_at) VALUES (?, ?)",
                (name, ts),
            )
            conn.commit()
            return {"id": cur.lastrowid, "name": name, "created_at": ts}
        finally:
            conn.close()


def list_portfolios() -> list[dict]:
    """Return all portfolios with nested projects."""
    conn = get_db()
    try:
        portfolios = [dict(r) for r in conn.execute(
            "SELECT id, name, created_at FROM portfolios ORDER BY id"
        ).fetchall()]
        projects = [dict(r) for r in conn.execute(
            "SELECT id, portfolio_id, name, repo_url, business_tier, user_type, created_at "
            "FROM projects ORDER BY id"
        ).fetchall()]
        project_map: dict[int, list] = {p["id"]: [] for p in portfolios}
        for pr in projects:
            pid = pr["portfolio_id"]
            if pid in project_map:
                project_map[pid].append(pr)
        for p in portfolios:
            p["projects"] = project_map[p["id"]]
        return portfolios
    finally:
        conn.close()


def delete_portfolio(portfolio_id: int) -> None:
    """Delete a portfolio and its projects."""
    with _lock:
        conn = get_db()
        try:
            conn.execute("DELETE FROM projects WHERE portfolio_id=?", (portfolio_id,))
            conn.execute("DELETE FROM portfolios WHERE id=?", (portfolio_id,))
            conn.commit()
        finally:
            conn.close()


def create_project(
    portfolio_id: int,
    name: str,
    repo_url: str | None = None,
    business_tier: str = "Tier 1",
    user_type: str = "external_customers",
) -> dict:
    """Insert a project row. Returns the full project dict."""
    with _lock:
        conn = get_db()
        try:
            ts = datetime.now().isoformat()
            cur = conn.execute(
                """
                INSERT INTO projects
                    (portfolio_id, name, repo_url, business_tier, user_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (portfolio_id, name, repo_url, business_tier, user_type, ts),
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "portfolio_id": portfolio_id,
                "name": name,
                "repo_url": repo_url,
                "business_tier": business_tier,
                "user_type": user_type,
                "created_at": ts,
            }
        finally:
            conn.close()


def update_project(
    project_id: int,
    repo_url=_UNSET,
    business_tier=_UNSET,
    user_type=_UNSET,
) -> None:
    """Update mutable project fields. Fields left as _UNSET are not changed.
    Pass None explicitly to clear a nullable field (e.g. repo_url=None)."""
    sets: list[str] = []
    params: list = []
    if repo_url is not _UNSET:
        sets.append("repo_url=?")
        params.append(repo_url)
    if business_tier is not _UNSET:
        sets.append("business_tier=?")
        params.append(business_tier)
    if user_type is not _UNSET:
        sets.append("user_type=?")
        params.append(user_type)
    if not sets:
        return
    params.append(project_id)
    with _lock:
        conn = get_db()
        try:
            conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", params)
            conn.commit()
        finally:
            conn.close()


def delete_project(project_id: int) -> None:
    """Delete a single project row."""
    with _lock:
        conn = get_db()
        try:
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.commit()
        finally:
            conn.close()


def backfill_telemetry_scan_id(run_id: str, scan_id: int) -> None:
    """Set scan_id on all telemetry spans for a run_id after save_scan() returns."""
    with _lock:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE telemetry SET scan_id=? WHERE run_id=?",
                (scan_id, run_id),
            )
            conn.commit()
        finally:
            conn.close()


def get_telemetry_summary(workspace_id: int, n_scans: int = 20) -> dict:
    """
    Return aggregated telemetry for the last n_scans scans of this workspace.

    Returns:
        last_scan_latency: {agent: duration_ms} for the most recent scan_id
        agent_avg_ms:      {agent: avg_duration_ms} across last n_scans
        error_rate:        fraction of spans that had an error (0.0–1.0)
        quality_trend:     [{timestamp, overall_score}] from eval_history (last 20)
        total_spans:       total telemetry spans recorded for this workspace
    """
    conn = get_db()
    try:
        # Identify the last N distinct runs for this workspace (by run_id)
        run_rows = conn.execute(
            """
            SELECT DISTINCT run_id, MAX(id) AS max_id FROM telemetry
            WHERE workspace_id=? AND run_id IS NOT NULL
            GROUP BY run_id
            ORDER BY max_id DESC LIMIT ?
            """,
            (workspace_id, n_scans),
        ).fetchall()
        run_ids = [r["run_id"] for r in run_rows]

        if not run_ids:
            spans = []
        else:
            placeholders = ",".join("?" * len(run_ids))
            spans = conn.execute(
                f"""
                SELECT agent, duration_ms, prompt_tokens, completion_tokens,
                       error, run_id, cost_usd
                FROM telemetry
                WHERE workspace_id=? AND run_id IN ({placeholders})
                ORDER BY id ASC
                """,
                [workspace_id, *run_ids],
            ).fetchall()

        spans = [dict(s) for s in spans]

        # Last scan latency breakdown — spans from the most recent run_id
        last_run_id = run_ids[0] if run_ids else None
        last_scan_latency = {
            s["agent"]: round(s["duration_ms"], 1)
            for s in spans if s["run_id"] == last_run_id
        }

        # Average latency per agent across all retrieved scans
        from collections import defaultdict
        agent_totals: dict[str, list[float]] = defaultdict(list)
        for s in spans:
            agent_totals[s["agent"]].append(s["duration_ms"])
        agent_avg_ms = {
            agent: round(sum(vals) / len(vals), 1)
            for agent, vals in agent_totals.items()
        }

        # Error rate (across all retrieved runs)
        total = len(spans)
        errors = sum(1 for s in spans if s["error"])
        error_rate = round(errors / total, 3) if total else 0.0

        # Quality trend from eval_history
        eval_rows = conn.execute(
            """
            SELECT timestamp, overall_score, overall_passed
            FROM eval_history WHERE workspace_id=?
            ORDER BY timestamp DESC LIMIT 20
            """,
            (workspace_id,),
        ).fetchall()
        quality_trend = [
            {"timestamp": r["timestamp"], "score": round(r["overall_score"] or 0, 3), "passed": bool(r["overall_passed"])}
            for r in reversed(eval_rows)
        ]

        # Cost summary — per-run totals for trend + last scan breakdown
        cost_summary: dict = {
            "last_scan_usd": 0.0,
            "per_agent_usd": {},
            "cost_trend": [],
            "projected_monthly_usd": 0.0,
        }
        if run_ids:
            run_cost_rows = conn.execute(
                f"""
                SELECT run_id, SUM(cost_usd) AS total_usd, MAX(ts) AS run_ts
                FROM telemetry
                WHERE workspace_id=? AND run_id IN ({placeholders})
                GROUP BY run_id
                ORDER BY run_ts ASC
                """,
                [workspace_id, *run_ids],
            ).fetchall()
            run_cost_rows = [dict(r) for r in run_cost_rows]

            per_agent: dict[str, float] = {}
            for s in spans:
                if s["run_id"] == last_run_id:
                    agent = s["agent"]
                    per_agent[agent] = round(per_agent.get(agent, 0.0) + (s["cost_usd"] or 0.0), 6)

            last_scan_usd = next(
                (r["total_usd"] or 0.0 for r in run_cost_rows if r["run_id"] == last_run_id), 0.0
            )

            cost_trend = [
                {"timestamp": r["run_ts"], "total_usd": round(r["total_usd"] or 0.0, 6)}
                for r in run_cost_rows
            ]

            projected = 0.0
            if len(run_cost_rows) >= 2:
                from datetime import datetime as _dt
                t_first = _dt.fromisoformat(run_cost_rows[0]["run_ts"])
                t_last  = _dt.fromisoformat(run_cost_rows[-1]["run_ts"])
                span_days = max((t_last - t_first).total_seconds() / 86400, 1 / 24)
                avg_cost = sum(r["total_usd"] or 0.0 for r in run_cost_rows) / len(run_cost_rows)
                projected = round(avg_cost * (len(run_cost_rows) / span_days) * 30, 2)

            cost_summary = {
                "last_scan_usd":        round(last_scan_usd, 6),
                "per_agent_usd":        per_agent,
                "cost_trend":           cost_trend,
                "projected_monthly_usd": projected,
            }

        return {
            "last_scan_latency": last_scan_latency,
            "agent_avg_ms": agent_avg_ms,
            "error_rate": error_rate,
            "quality_trend": quality_trend,
            "total_spans": total,
            "cost_summary": cost_summary,
        }
    finally:
        conn.close()
