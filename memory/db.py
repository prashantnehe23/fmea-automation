"""
memory/db.py — SQLite persistence layer for FMEA scan results.

Database file: memory/fmea.db (next to this module).

Tables:
  workspaces    — customer/project identity
  scans         — full pipeline result JSON, one row per run
  scenarios     — locked failure mode registry with embeddings for semantic dedup
  eval_history  — pipeline eval scores per scan
  scan_snapshots / scan_sources — full findings + scanned files, for the results chat (B-025)
  chat_threads / chat_messages  — persistent conversation per project (B-025)
  chat_proposals                — changes the chat model proposed; applied only on user click (B-025)

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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from core.paths import data_dir
from core.priority import lowers_catastrophic_severity

_DB_PATH = data_dir(Path(__file__).resolve().parent) / "fmea.db"
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

CREATE TABLE IF NOT EXISTS scan_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  INTEGER NOT NULL REFERENCES workspaces(id),
    scan_id       INTEGER,
    fingerprint   TEXT    NOT NULL,
    findings_json TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    UNIQUE(workspace_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS scan_sources (
    snapshot_id INTEGER NOT NULL REFERENCES scan_snapshots(id),
    path        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    PRIMARY KEY (snapshot_id, path)
);

CREATE TABLE IF NOT EXISTS chat_threads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL UNIQUE REFERENCES workspaces(id),
    summary      TEXT,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id         INTEGER NOT NULL REFERENCES chat_threads(id),
    role              TEXT    NOT NULL,
    message_json      TEXT    NOT NULL,
    snapshot_id       INTEGER,
    activity_json     TEXT,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost_usd          REAL    DEFAULT 0,
    summarised        INTEGER DEFAULT 0,
    created_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_proposals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id    INTEGER NOT NULL REFERENCES chat_threads(id),
    message_id   INTEGER,
    snapshot_id  INTEGER,
    kind         TEXT    NOT NULL,
    failure_mode TEXT    NOT NULL,
    payload_json TEXT    NOT NULL,
    reason       TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'proposed',
    result_json  TEXT,
    created_at   TEXT    NOT NULL,
    decided_at   TEXT
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

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT    NOT NULL,
    role          TEXT    NOT NULL,
    password_hash TEXT,
    oidc_subject  TEXT    UNIQUE,
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS finding_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    scenario_id  INTEGER,
    failure_mode TEXT    NOT NULL,
    from_state   TEXT,
    to_state     TEXT    NOT NULL,
    scan_id      INTEGER,
    actor        TEXT,
    note         TEXT,
    at           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    token_hash   TEXT    NOT NULL UNIQUE,
    hint         TEXT    NOT NULL,
    created_by   TEXT,
    created_at   TEXT    NOT NULL,
    last_used_at TEXT,
    revoked      INTEGER NOT NULL DEFAULT 0,
    scope_repo   TEXT
);

CREATE TABLE IF NOT EXISTS pr_check_config (
    project_id    INTEGER PRIMARY KEY,
    enabled       INTEGER NOT NULL DEFAULT 1,
    fail_severity INTEGER NOT NULL DEFAULT 9,
    budget_usd    REAL    NOT NULL DEFAULT 1.0,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT    NOT NULL,
    user_id  INTEGER,
    username TEXT,
    action   TEXT    NOT NULL,
    detail   TEXT
);

CREATE TABLE IF NOT EXISTS oidc_logins (
    state         TEXT PRIMARY KEY,
    nonce         TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    created_at    TEXT NOT NULL
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
        "ALTER TABLE adjustments ADD COLUMN source TEXT DEFAULT 'manual'",
        "ALTER TABLE adjustments ADD COLUMN flagged INTEGER DEFAULT 0",
        "ALTER TABLE adjustments ADD COLUMN adjusted_by TEXT",
        "ALTER TABLE scenarios ADD COLUMN identity_key TEXT",
        "ALTER TABLE scenarios ADD COLUMN state TEXT DEFAULT 'confirmed'",     # B-031: existing rows count as confirmed
        "ALTER TABLE scenarios ADD COLUMN state_scan_id INTEGER",
        "ALTER TABLE scenarios ADD COLUMN state_changed_at TEXT",
        "ALTER TABLE chat_proposals ADD COLUMN decided_by TEXT",
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
            ORDER BY timestamp DESC, id DESC LIMIT 1
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
            ORDER BY timestamp DESC, id DESC
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
    identity_key: str | None = None,
) -> None:
    """
    Insert scenario if not present (keyed on workspace_id + failure_mode), as a `new` finding (B-031).
    Does NOT update on conflict — the first scan's scores are the canonical ones.
    """
    with _lock:
        conn = get_db()
        try:
            if identity_key and conn.execute("SELECT 1 FROM scenarios WHERE workspace_id=? AND identity_key=?",
                                             (workspace_id, identity_key)).fetchone():
                identity_key = None        # another finding already owns this quote: do not let two share an identity
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO scenarios
                    (workspace_id, first_fingerprint, failure_mode, attack_chain_json,
                     severity, occurrence, detection, rpn, embedding, embed_model, created_at,
                     identity_key, state, state_changed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
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
                    identity_key,
                    datetime.now().isoformat(),
                ),
            )
            if cur.rowcount == 1:
                conn.execute("INSERT INTO finding_events (workspace_id, scenario_id, failure_mode, from_state, to_state,"
                             " note, at) VALUES (?, ?, ?, NULL, 'new', 'first reported', ?)",
                             (workspace_id, cur.lastrowid, failure_mode, datetime.now().isoformat()))
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
            SELECT id, failure_mode, attack_chain_json, severity, occurrence, detection, rpn, embedding, embed_model,
                   identity_key, COALESCE(state, 'confirmed') AS state, state_scan_id, state_changed_at
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


def set_scenario_state(workspace_id: int, failure_mode: str, state: str, scan_id: int | None = None,
                       actor: str | None = None, note: str = "", only_if_state: str | None = None) -> bool:
    """Move a finding to a new lifecycle state and record who or which scan caused it (B-031).

    With only_if_state the move happens only if the finding is still in that state, so a scan working from an
    earlier snapshot never overwrites a decision a person made meanwhile, and two scans never both apply it."""
    with _lock:
        conn = get_db()
        try:
            row = conn.execute("SELECT id, COALESCE(state, 'confirmed') AS state FROM scenarios"
                               " WHERE workspace_id=? AND failure_mode=?", (workspace_id, failure_mode)).fetchone()
            if row is None or (only_if_state is not None and row["state"] != only_if_state):
                return False
            now = datetime.now().isoformat()
            conn.execute("UPDATE scenarios SET state=?, state_scan_id=?, state_changed_at=? WHERE id=?",
                         (state, scan_id, now, row["id"]))
            conn.execute("INSERT INTO finding_events (workspace_id, scenario_id, failure_mode, from_state, to_state,"
                         " scan_id, actor, note, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (workspace_id, row["id"], failure_mode, row["state"], state, scan_id, actor, note, now))
            conn.commit()
            return True
        finally:
            conn.close()


def set_identity_key(workspace_id: int, failure_mode: str, identity_key: str) -> None:
    """Record the identity of an existing finding (rows saved before B-031 have none). Never gives two
    findings of a project the same identity."""
    with _lock:
        conn = get_db()
        try:
            conn.execute("UPDATE scenarios SET identity_key=? WHERE workspace_id=? AND failure_mode=?"
                         " AND identity_key IS NULL AND NOT EXISTS"
                         " (SELECT 1 FROM scenarios WHERE workspace_id=? AND identity_key=?)",
                         (identity_key, workspace_id, failure_mode, workspace_id, identity_key))
            conn.commit()
        finally:
            conn.close()


def list_finding_events(workspace_id: int, limit: int = 500) -> list[dict]:
    """State history of a project's findings, oldest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT failure_mode, from_state, to_state, scan_id, actor, note, at FROM finding_events"
            " WHERE workspace_id=? ORDER BY id DESC LIMIT ?", (workspace_id, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


def delete_scenarios(workspace_id: int) -> None:
    """Wipe all locked scenarios for this workspace (user-triggered unlock)."""
    with _lock:
        conn = get_db()
        try:
            now = datetime.now().isoformat()
            conn.execute("INSERT INTO finding_events (workspace_id, scenario_id, failure_mode, from_state, to_state, note, at)"
                         " SELECT workspace_id, id, failure_mode, COALESCE(state, 'confirmed'), 'removed', 'unlocked', ?"
                         " FROM scenarios WHERE workspace_id=?", (now, workspace_id))
            conn.execute("DELETE FROM scenarios WHERE workspace_id=?", (workspace_id,))
            conn.commit()
        finally:
            conn.close()


def delete_scenario(workspace_id: int, failure_mode: str) -> bool:
    """Unlock one scenario (its locked scores are dropped; the next scan re-scores it).
    Returns True if a locked scenario was removed."""
    with _lock:
        conn = get_db()
        try:
            conn.execute("INSERT INTO finding_events (workspace_id, scenario_id, failure_mode, from_state, to_state, note, at)"
                         " SELECT workspace_id, id, failure_mode, COALESCE(state, 'confirmed'), 'removed', 'unlocked', ?"
                         " FROM scenarios WHERE workspace_id=? AND failure_mode=?",
                         (datetime.now().isoformat(), workspace_id, failure_mode))
            cur = conn.execute(
                "DELETE FROM scenarios WHERE workspace_id=? AND failure_mode=?",
                (workspace_id, failure_mode),
            )
            conn.commit()
            return cur.rowcount > 0
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
            ORDER BY timestamp DESC, id DESC LIMIT ?
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
    source: str = "manual",
    adjusted_by: str | None = None,
) -> int:
    """Persist a score adjustment (source: "manual" or "chat"). Returns adjustment id.

    An adjustment that takes a Severity >= 9 scenario below 9 is flagged for the audit trail (B-034)."""
    new_rpn = new_s * new_o * new_d
    current = get_current_severity(workspace_id, failure_mode)
    flagged = int(current is not None and lowers_catastrophic_severity(current, new_s))
    with _lock:
        conn = get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO adjustments
                    (workspace_id, failure_mode, new_s, new_o, new_d, new_rpn, justification, created_at,
                     source, flagged, adjusted_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (workspace_id, failure_mode, new_s, new_o, new_d, new_rpn,
                 justification, datetime.now().isoformat(), source or "manual", flagged, adjusted_by),
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
            SELECT id, failure_mode, new_s, new_o, new_d, new_rpn, justification, created_at,
                   COALESCE(source, 'manual') AS source, COALESCE(flagged, 0) AS flagged, adjusted_by
            FROM adjustments WHERE workspace_id=?
            ORDER BY created_at DESC, id DESC
            """,
            (workspace_id,),
        ).fetchall()
        return [{**dict(r), "flagged": bool(r["flagged"])} for r in rows]
    finally:
        conn.close()


def get_current_severity(workspace_id: int, failure_mode: str) -> int | None:
    """Severity in force for a scenario: the latest adjustment, else its registry score, else None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT new_s FROM adjustments WHERE workspace_id=? AND failure_mode=? "
            "ORDER BY created_at DESC, id DESC LIMIT 1", (workspace_id, failure_mode)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT severity AS new_s FROM scenarios WHERE workspace_id=? AND failure_mode=?",
                (workspace_id, failure_mode)).fetchone()
        return int(row["new_s"]) if row else None
    finally:
        conn.close()


# ── Results chat (B-025) ──────────────────────────────────────────────────────

def save_scan_snapshot(
    workspace_id: int,
    scan_id: int | None,
    fingerprint: str,
    findings: dict,
    files: dict[str, str],
) -> int:
    """Persist a scan's full findings and source files. Upserts on (workspace, fingerprint)."""
    with _lock:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id FROM scan_snapshots WHERE workspace_id=? AND fingerprint=?",
                (workspace_id, fingerprint),
            ).fetchone()
            now = datetime.now().isoformat()
            findings_json = json.dumps(findings, default=str)
            if row:
                snapshot_id = row["id"]
                conn.execute(
                    "UPDATE scan_snapshots SET scan_id=?, findings_json=?, created_at=? WHERE id=?",
                    (scan_id, findings_json, now, snapshot_id),
                )
                conn.execute("DELETE FROM scan_sources WHERE snapshot_id=?", (snapshot_id,))
            else:
                cur = conn.execute(
                    """INSERT INTO scan_snapshots
                           (workspace_id, scan_id, fingerprint, findings_json, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (workspace_id, scan_id, fingerprint, findings_json, now),
                )
                snapshot_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO scan_sources (snapshot_id, path, content) VALUES (?, ?, ?)",
                [(snapshot_id, path, content) for path, content in files.items()],
            )
            conn.commit()
            return snapshot_id  # type: ignore[return-value]
        finally:
            conn.close()


def get_project_scan(project_id: int) -> dict | None:
    """Latest stored scan of a project, in the shape the UI keeps per project (B-015), or None."""
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT w.id AS workspace_id, pr.repo_url AS repo_url
               FROM projects pr JOIN portfolios po ON po.id = pr.portfolio_id
               JOIN workspaces w ON w.customer = po.name AND w.project = pr.name
               WHERE pr.id = ?""",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    snap = get_latest_snapshot(row["workspace_id"])
    if not snap:
        return None
    result = snap["findings"]
    risks = result.get("risks") or []
    new = result.get("new_scenarios") or []
    return {
        "scanId": snap["scan_id"], "repoUrl": row["repo_url"], "timestamp": snap["created_at"],
        "risk_count": len(risks), "max_rpn": max((r.get("rpn", 0) for r in risks), default=0),
        "from_cache": bool(result.get("from_cache", False)),
        "registry_locked": bool(result.get("registry_locked", False)),
        "locked_count": len(risks) - len(new), "workspace_id": row["workspace_id"], "result": result,
    }


def project_exists(project_id: int) -> bool:
    conn = get_db()
    try:
        return conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is not None
    finally:
        conn.close()


def find_project_by_repo(owner: str, repo: str) -> dict | None:
    """The project whose repository is github.com/owner/repo (case-insensitive), with its workspace id if it has one."""
    wanted = f"{owner}/{repo}".lower().removesuffix(".git")
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT pr.id, pr.name, pr.repo_url, pr.business_tier, pr.user_type, po.name AS portfolio_name,
                      (SELECT w.id FROM workspaces w WHERE w.customer = po.name AND w.project = pr.name) AS workspace_id
               FROM projects pr JOIN portfolios po ON po.id = pr.portfolio_id WHERE pr.repo_url IS NOT NULL""").fetchall()
    finally:
        conn.close()
    for r in rows:
        url = (r["repo_url"] or "").strip().rstrip("/").lower().removesuffix(".git")
        for prefix in ("https://github.com/", "http://github.com/"):
            if url.startswith(prefix) and url[len(prefix):].split("/tree/")[0] == wanted:
                return dict(r)
    return None


def get_pr_check_config(project_id: int) -> dict:
    """Pull-request check settings of a project; defaults when none were saved (B-012)."""
    conn = get_db()
    try:
        row = conn.execute("SELECT enabled, fail_severity, budget_usd FROM pr_check_config WHERE project_id=?",
                           (project_id,)).fetchone()
    finally:
        conn.close()
    return {"enabled": bool(row["enabled"]), "fail_severity": row["fail_severity"], "budget_usd": row["budget_usd"]} \
        if row else {"enabled": True, "fail_severity": 9, "budget_usd": 1.0}


def set_pr_check_config(project_id: int, enabled: bool | None = None, fail_severity: int | None = None,
                        budget_usd: float | None = None) -> dict:
    current = get_pr_check_config(project_id)
    new = {"enabled": current["enabled"] if enabled is None else enabled,
           "fail_severity": current["fail_severity"] if fail_severity is None else fail_severity,
           "budget_usd": current["budget_usd"] if budget_usd is None else budget_usd}
    with _lock:
        conn = get_db()
        try:
            conn.execute("INSERT INTO pr_check_config (project_id, enabled, fail_severity, budget_usd, updated_at)"
                         " VALUES (?, ?, ?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET enabled=excluded.enabled,"
                         " fail_severity=excluded.fail_severity, budget_usd=excluded.budget_usd, updated_at=excluded.updated_at",
                         (project_id, int(new["enabled"]), new["fail_severity"], new["budget_usd"], datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()
    return new


def purge_expired_sources(days: int) -> int:
    """Delete scanned source files of snapshots older than *days* (B-042). Findings are kept. Returns files deleted."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with _lock:
        conn = get_db()
        try:
            cur = conn.execute(
                "DELETE FROM scan_sources WHERE snapshot_id IN (SELECT id FROM scan_snapshots WHERE created_at < ?)",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def delete_sources_for_workspace(workspace_id: int) -> int:
    """Delete every stored source file of a project (B-042). Returns files deleted."""
    with _lock:
        conn = get_db()
        try:
            cur = conn.execute(
                "DELETE FROM scan_sources WHERE snapshot_id IN (SELECT id FROM scan_snapshots WHERE workspace_id=?)",
                (workspace_id,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def workspace_exists(workspace_id: int) -> bool:
    conn = get_db()
    try:
        return conn.execute("SELECT 1 FROM workspaces WHERE id=?", (workspace_id,)).fetchone() is not None
    finally:
        conn.close()


def get_latest_snapshot(workspace_id: int) -> dict | None:
    """Most recent snapshot for a project: {id, scan_id, fingerprint, findings, created_at}."""
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT id, scan_id, fingerprint, findings_json, created_at FROM scan_snapshots
               WHERE workspace_id=? ORDER BY created_at DESC, id DESC LIMIT 1""",
            (workspace_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["findings"] = json.loads(item.pop("findings_json"))
        return item
    finally:
        conn.close()


def get_snapshot_files(snapshot_id: int) -> dict[str, str]:
    """Return {path: content} for a snapshot, ordered by path."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT path, content FROM scan_sources WHERE snapshot_id=? ORDER BY path",
            (snapshot_id,),
        ).fetchall()
        return {r["path"]: r["content"] for r in rows}
    finally:
        conn.close()


def get_or_create_chat_thread(workspace_id: int) -> dict:
    """The single chat thread of a project: {id, workspace_id, summary}."""
    with _lock:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id, workspace_id, summary FROM chat_threads WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            if row:
                return dict(row)
            cur = conn.execute(
                "INSERT INTO chat_threads (workspace_id, created_at) VALUES (?, ?)",
                (workspace_id, datetime.now().isoformat()),
            )
            conn.commit()
            return {"id": cur.lastrowid, "workspace_id": workspace_id, "summary": None}
        finally:
            conn.close()


def add_chat_message(
    thread_id: int,
    message: dict,
    snapshot_id: int | None = None,
    activity: list | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
) -> int:
    """Append an OpenAI-format message ({"role", "content", ...}) to a thread."""
    with _lock:
        conn = get_db()
        try:
            cur = conn.execute(
                """INSERT INTO chat_messages
                       (thread_id, role, message_json, snapshot_id, activity_json,
                        prompt_tokens, completion_tokens, cost_usd, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (thread_id, message["role"], json.dumps(message, default=str), snapshot_id,
                 json.dumps(activity) if activity else None,
                 prompt_tokens, completion_tokens, cost_usd, datetime.now().isoformat()),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        finally:
            conn.close()


def get_chat_messages(thread_id: int, include_summarised: bool = False) -> list[dict]:
    """Messages oldest first: {id, role, message, snapshot_id, activity, tokens, cost_usd, ...}."""
    conn = get_db()
    try:
        sql = "SELECT * FROM chat_messages WHERE thread_id=?"
        if not include_summarised:
            sql += " AND summarised=0"
        rows = conn.execute(sql + " ORDER BY id", (thread_id,)).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["message"] = json.loads(item.pop("message_json"))
            item["activity"] = json.loads(item.pop("activity_json") or "[]")
            out.append(item)
        return out
    finally:
        conn.close()


def fold_chat_history(thread_id: int, up_to_message_id: int, summary: str) -> None:
    """Replace messages up to an id with a summary (they stay stored, flagged summarised)."""
    with _lock:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE chat_messages SET summarised=1 WHERE thread_id=? AND id<=?",
                (thread_id, up_to_message_id),
            )
            conn.execute("UPDATE chat_threads SET summary=? WHERE id=?", (summary, thread_id))
            conn.commit()
        finally:
            conn.close()


def get_chat_totals(thread_id: int) -> dict:
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT COALESCE(SUM(prompt_tokens),0) p, COALESCE(SUM(completion_tokens),0) c,
                      COALESCE(SUM(cost_usd),0) cost FROM chat_messages WHERE thread_id=?""",
            (thread_id,),
        ).fetchone()
        return {"prompt_tokens": row["p"], "completion_tokens": row["c"],
                "cost_usd": round(row["cost"], 6)}
    finally:
        conn.close()


def get_chat_thread(thread_id: int) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT id, workspace_id, summary FROM chat_threads WHERE id=?",
                           (thread_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_proposal_result(proposal_id: int, result: dict) -> None:
    with _lock:
        conn = get_db()
        try:
            conn.execute("UPDATE chat_proposals SET result_json=? WHERE id=?",
                         (json.dumps(result), proposal_id))
            conn.commit()
        finally:
            conn.close()


def create_proposal(thread_id: int, snapshot_id: int | None, kind: str, failure_mode: str,
                    payload: dict, reason: str) -> int:
    """Record a change proposed by the chat model. Nothing is applied until the user decides."""
    with _lock:
        conn = get_db()
        try:
            cur = conn.execute(
                """INSERT INTO chat_proposals
                       (thread_id, snapshot_id, kind, failure_mode, payload_json, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (thread_id, snapshot_id, kind, failure_mode, json.dumps(payload), reason,
                 datetime.now().isoformat()),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        finally:
            conn.close()


def _proposal_row(row) -> dict:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    item["result"] = json.loads(item.pop("result_json") or "null")
    return item


def get_proposal(proposal_id: int) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM chat_proposals WHERE id=?", (proposal_id,)).fetchone()
        return _proposal_row(row) if row else None
    finally:
        conn.close()


def list_proposals(thread_id: int) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM chat_proposals WHERE thread_id=? ORDER BY id", (thread_id,)
        ).fetchall()
        return [_proposal_row(r) for r in rows]
    finally:
        conn.close()


def attach_proposals_to_message(proposal_ids: list[int], message_id: int) -> None:
    if not proposal_ids:
        return
    with _lock:
        conn = get_db()
        try:
            conn.executemany("UPDATE chat_proposals SET message_id=? WHERE id=?",
                             [(message_id, pid) for pid in proposal_ids])
            conn.commit()
        finally:
            conn.close()


def decide_proposal(proposal_id: int, new_status: str, result: dict | None = None,
                    decided_by: str | None = None) -> bool:
    """Atomically move a proposal out of 'proposed'. Returns False if it was already decided,
    which is what makes Apply / Dismiss idempotent even under concurrent clicks."""
    with _lock:
        conn = get_db()
        try:
            cur = conn.execute(
                """UPDATE chat_proposals SET status=?, result_json=?, decided_at=?, decided_by=?
                   WHERE id=? AND status='proposed'""",
                (new_status, json.dumps(result) if result is not None else None,
                 datetime.now().isoformat(), decided_by, proposal_id),
            )
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()


def reopen_proposal(proposal_id: int) -> None:
    """Undo a claim when applying failed, so the user can retry."""
    with _lock:
        conn = get_db()
        try:
            conn.execute("UPDATE chat_proposals SET status='proposed', result_json=NULL, decided_at=NULL, decided_by=NULL WHERE id=?",
                         (proposal_id,))
            conn.commit()
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
            ORDER BY timestamp DESC, id DESC LIMIT 20
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

        # Chat spend (B-025) is recorded as agent "chat" spans outside any scan run
        chat_row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS usd, COUNT(*) AS n FROM telemetry "
            "WHERE workspace_id=? AND agent='chat'", (workspace_id,)
        ).fetchone()
        cost_summary["chat_usd"] = round(chat_row["usd"], 6)
        cost_summary["chat_turns"] = chat_row["n"]

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
