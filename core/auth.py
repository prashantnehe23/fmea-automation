"""
core/auth.py — B-015 (ADR-027): users, password hashing, server-side sessions.

Passwords: standard-library scrypt with a per-user salt, constant-time comparison.
Sessions: a random token in an HttpOnly cookie; only its SHA-256 is stored, so a leaked database
does not leak live sessions. Disabling a user ends their sessions at once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime, timedelta

import memory.db as db

ROLES = ("admin", "security_engineer", "risk_manager", "developer", "viewer")
MIN_PASSWORD_LENGTH = 10
SESSION_DAYS = 7
MAX_FAILURES, FAILURE_WINDOW_SECONDS, MAX_TRACKED = 5, 15 * 60, 5000

_setup_lock = threading.Lock()
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()
_N, _R, _P = 2 ** 14, 8, 1


class AuthError(Exception):
    """A request the user can fix: bad input or a rule such as 'keep one admin'. .status is the HTTP code."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ── passwords ─────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str | None) -> bool:
    try:
        _, n, r, p, salt, digest = (stored or "").split("$")
        candidate = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except Exception:
        return False


_DUMMY_HASH = hash_password("not-a-real-password")


# ── users ─────────────────────────────────────────────────────────────────────

def _public(row) -> dict:
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"], "role": row["role"],
            "disabled": bool(row["disabled"]), "sign_in": "single sign-on" if row["oidc_subject"] else "password"}


def _query(sql: str, args: tuple = ()):
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def count_users() -> int:
    return _query("SELECT COUNT(*) AS n FROM users")[0]["n"]


def list_users() -> list[dict]:
    return [_public(r) for r in _query("SELECT * FROM users ORDER BY id")]


def get_user(user_id: int) -> dict | None:
    rows = _query("SELECT * FROM users WHERE id=?", (user_id,))
    return _public(rows[0]) if rows else None


def create_user(username: str, password: str | None, role: str, display_name: str | None = None,
                oidc_subject: str | None = None) -> dict:
    username = (username or "").strip()
    if not username or len(username) > 100:
        raise AuthError("Enter a username of up to 100 characters.")
    if role not in ROLES:
        raise AuthError(f"Role must be one of: {', '.join(ROLES)}.")
    if password is not None and len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
    with db._lock:
        conn = db.get_db()
        try:
            if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise AuthError("That username is taken.", 409)
            cur = conn.execute(
                "INSERT INTO users (username, display_name, role, password_hash, oidc_subject, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (username, (display_name or username).strip(), role,
                 hash_password(password) if password is not None else None, oidc_subject,
                 datetime.now().isoformat()),
            )
            conn.commit()
            user_id = cur.lastrowid
        finally:
            conn.close()
    return get_user(user_id)  # type: ignore[arg-type]


def update_user(user_id: int, role: str | None = None, disabled: bool | None = None,
                password: str | None = None, via_idp: bool = False) -> dict:
    current = get_user(user_id)
    if current is None:
        raise AuthError("Unknown user.", 404)
    if current["sign_in"] == "single sign-on" and not via_idp and (role is not None or password is not None):
        raise AuthError("Role and password of a single sign-on user are managed by the identity provider.", 409)
    if role is not None and role not in ROLES:
        raise AuthError(f"Role must be one of: {', '.join(ROLES)}.")
    if password is not None and len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
    loses_admin = current["role"] == "admin" and not current["disabled"] and (
        (role is not None and role != "admin") or disabled is True)
    with db._lock:
        conn = db.get_db()
        try:
            if loses_admin and conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0 AND id<>?", (user_id,)).fetchone()[0] == 0:
                raise AuthError("There must be at least one active administrator.", 409)
            if role is not None:
                conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
            if disabled is not None:
                conn.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), user_id))
            if password is not None:
                conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id))
            if disabled or password is not None:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.commit()
        finally:
            conn.close()
    return get_user(user_id)  # type: ignore[return-value]


# ── sign-in ───────────────────────────────────────────────────────────────────

def reset_login_throttle() -> None:
    with _failures_lock:
        _failures.clear()


def _recent_failures(key: str) -> list[float]:
    cutoff = time.time() - FAILURE_WINDOW_SECONDS
    kept = [t for t in _failures.get(key, []) if t > cutoff]
    if kept:
        _failures[key] = kept
    else:
        _failures.pop(key, None)
    return kept


def _track(key: str) -> None:
    """Record a failed attempt; the table is bounded so spraying random names cannot grow memory."""
    if len(_failures) >= MAX_TRACKED:
        for k in list(_failures):
            _recent_failures(k)
        if len(_failures) >= MAX_TRACKED:
            _failures.clear()
    _failures.setdefault(key, []).append(time.time())


def authenticate(username: str, password: str, client: str = "") -> dict | None:
    """The user for valid credentials, None for invalid ones. Raises AuthError(429) after repeated failures.

    Failures are counted per (client address, normalised username), so one client cannot lock a real
    user out of every other client."""
    username = username.strip()
    key = f"{client}|{username.lower()}"
    with _failures_lock:
        if len(_recent_failures(key)) >= MAX_FAILURES:
            raise AuthError("Too many failed attempts. Try again in a few minutes.", 429)
    rows = _query("SELECT * FROM users WHERE username=?", (username,))
    row = rows[0] if rows else None
    stored = (row["password_hash"] if row else None) or _DUMMY_HASH            # same work for every case
    ok = verify_password(password, stored)
    if row and ok and row["password_hash"] and not row["disabled"]:
        with _failures_lock:
            _failures.pop(key, None)
        return _public(row)
    with _failures_lock:
        _track(key)
    return None


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    with db._lock:
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
            conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                         (_hash(token), user_id, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat()))
            conn.commit()
        finally:
            conn.close()
    return token


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    rows = _query(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token_hash=? AND s.expires_at > ? AND u.disabled=0",
        (_hash(token), datetime.now().isoformat()),
    )
    return _public(rows[0]) if rows else None


def delete_session(token: str | None) -> None:
    if not token:
        return
    with db._lock:
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))
            conn.commit()
        finally:
            conn.close()


def has_active_admin() -> bool:
    return _query("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND disabled=0")[0]["n"] > 0


def setup_token_required() -> bool:
    return bool(os.environ.get("FMEA_SETUP_TOKEN", "").strip())


def create_api_token(name: str, created_by: str, repo: str | None = None) -> dict:
    """A token for CI: shown once, stored only as a hash. It may call the pull-request check and nothing else."""
    token = "fmea_" + secrets.token_urlsafe(32)
    with db._lock:
        conn = db.get_db()
        try:
            cur = conn.execute("INSERT INTO api_tokens (name, token_hash, hint, created_by, created_at, scope_repo)"
                               " VALUES (?, ?, ?, ?, ?, ?)",
                               (name, _hash(token), "••••" + token[-4:], created_by, datetime.now().isoformat(),
                                repo.lower() if repo else None))
            conn.commit()
            token_id = cur.lastrowid
        finally:
            conn.close()
    return {"id": token_id, "name": name, "token": token, "hint": "••••" + token[-4:], "repo": repo.lower() if repo else None}


def api_token_user(token: str) -> dict | None:
    rows = _query("SELECT id, name, scope_repo FROM api_tokens WHERE token_hash=? AND revoked=0", (_hash(token),))
    if not rows:
        return None
    try:
        with db._lock:
            conn = db.get_db()
            try:
                conn.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?", (datetime.now().isoformat(), rows[0]["id"]))
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass
    return {"id": None, "username": f"token:{rows[0]['name']}", "display_name": rows[0]["name"], "role": "ci",
            "token_id": rows[0]["id"], "scope_repo": rows[0]["scope_repo"]}


def list_api_tokens() -> list[dict]:
    return [{"id": r["id"], "name": r["name"], "hint": r["hint"], "created_by": r["created_by"],
             "created_at": r["created_at"], "last_used_at": r["last_used_at"], "revoked": bool(r["revoked"]),
             "repo": r["scope_repo"]}
            for r in _query("SELECT * FROM api_tokens ORDER BY id")]


def revoke_api_token(token_id: int) -> bool:
    with db._lock:
        conn = db.get_db()
        try:
            cur = conn.execute("UPDATE api_tokens SET revoked=1 WHERE id=? AND revoked=0", (token_id,))
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()


def bootstrap_admin_from_env() -> None:
    """Create the first administrator from FMEA_ADMIN_USER / FMEA_ADMIN_PASSWORD when none exists."""
    username, password = os.environ.get("FMEA_ADMIN_USER", "").strip(), os.environ.get("FMEA_ADMIN_PASSWORD", "")
    if not username or not password:
        return
    with _setup_lock:
        if not has_active_admin():
            create_user(username, password, "admin")


def create_first_admin(username: str, password: str, display_name: str | None, setup_token: str | None = None) -> dict:
    """First-run setup: allowed only while no active administrator exists (single-sign-on users do not count).
    When FMEA_SETUP_TOKEN is set the caller must present it, so whoever first reaches a new install
    cannot claim it."""
    expected = os.environ.get("FMEA_SETUP_TOKEN", "").strip()
    if expected and not hmac.compare_digest((setup_token or "").encode(), expected.encode()):
        raise AuthError("Wrong setup token.", 403)
    with _setup_lock:
        if has_active_admin():
            raise AuthError("Setup is already done.", 409)
        return create_user(username, password, "admin", display_name)


def record_event(user: dict | None, action: str, detail: str = "") -> None:
    """Append to the audit trail. Never put a secret in *detail*."""
    with db._lock:
        conn = db.get_db()
        try:
            conn.execute("INSERT INTO audit_events (ts, user_id, username, action, detail) VALUES (?, ?, ?, ?, ?)",
                         (datetime.now().isoformat(), (user or {}).get("id"), (user or {}).get("username"), action, detail))
            conn.commit()
        finally:
            conn.close()
