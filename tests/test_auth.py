"""
B-015 — sign-in, roles and server-side results (ADR-027).

  AC: every API route except health and sign-in returns 401 without a session (enumerating test)
  AC: role rules enforced on the server (developer cannot apply a score change or set a key)
  AC: a scan saved by one user is readable by another user of the install (server-side results)
  AC: adjustments and chat proposals record the signed-in user
  AC: existing data loads after migration
"""

import re
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import core.settings as settings
import memory.db as db

CSRF = {"X-Requested-With": "fmea"}
PASSWORD = "correct-horse-battery"


@pytest.fixture
def app(real_auth, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fmea.db")
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.delenv("FMEA_ADMIN_USER", raising=False)
    monkeypatch.delenv("FMEA_SETUP_TOKEN", raising=False)
    monkeypatch.setenv("FMEA_COOKIE_SECURE", "0")          # tests talk plain http
    from api.main import app as application
    from core import auth
    auth.reset_login_throttle()
    return application


def _client(app):
    return TestClient(app, headers=CSRF)


@pytest.fixture
def admin(app):
    c = _client(app)
    r = c.post("/api/auth/setup", json={"username": "root", "password": PASSWORD})
    assert r.status_code == 201, r.text
    return c


def _user(admin, username, role):
    r = admin.post("/api/users", json={"username": username, "password": PASSWORD, "role": role})
    assert r.status_code == 201, r.text
    c = TestClient(admin.app, headers=CSRF)
    assert c.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200
    return c


# ── sign-in basics ────────────────────────────────────────────────────────────

def test_first_run_setup_creates_the_admin_once(app):
    c = _client(app)
    assert c.get("/api/auth/status").json()["setup_required"] is True
    assert c.post("/api/auth/setup", json={"username": "root", "password": "short"}).status_code == 422
    r = c.post("/api/auth/setup", json={"username": "root", "password": PASSWORD})
    assert r.status_code == 201 and r.json()["role"] == "admin"
    assert c.get("/api/auth/me").json()["username"] == "root"           # setup signs the admin in
    assert _client(app).post("/api/auth/setup", json={"username": "x", "password": PASSWORD}).status_code == 409
    assert _client(app).get("/api/auth/status").json()["setup_required"] is False


def test_login_logout_and_wrong_password(app, admin):
    other = _client(app)
    assert other.post("/api/auth/login", json={"username": "root", "password": "wrong-password-1"}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "nobody", "password": PASSWORD}).status_code == 401
    r = other.post("/api/auth/login", json={"username": "ROOT", "password": PASSWORD})     # case-insensitive name
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert other.get("/api/auth/me").status_code == 200
    other.post("/api/auth/logout")
    assert other.get("/api/auth/me").status_code == 401


def test_password_is_stored_hashed_and_never_returned(app, admin):
    conn = sqlite3.connect(db._DB_PATH)
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert PASSWORD not in stored and stored.startswith("scrypt$")
    assert PASSWORD not in admin.get("/api/users").text


def test_repeated_failures_lock_the_account_temporarily(app, admin):
    c = _client(app)
    codes = [c.post("/api/auth/login", json={"username": "root", "password": "bad-password-00"}).status_code
             for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[-1] == 429
    assert c.post("/api/auth/login", json={"username": "root", "password": PASSWORD}).status_code == 429


def test_disabled_user_loses_access_immediately(app, admin):
    dev = _user(admin, "dana", "developer")
    uid = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "dana")
    assert dev.get("/api/portfolios").status_code == 200
    assert admin.patch(f"/api/users/{uid}", json={"disabled": True}).status_code == 200
    assert dev.get("/api/portfolios").status_code == 401


def test_the_last_active_admin_cannot_be_demoted_or_disabled(app, admin):
    uid = admin.get("/api/auth/me").json()["id"]
    assert admin.patch(f"/api/users/{uid}", json={"role": "viewer"}).status_code == 409
    assert admin.patch(f"/api/users/{uid}", json={"disabled": True}).status_code == 409


# ── every route needs a session ───────────────────────────────────────────────

def _routes(app):
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield m, r.path


def _concrete(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_route_has_a_policy_entry(app):
    from api.policy import POLICY
    missing = [(m, p) for m, p in _routes(app) if (m, p) not in POLICY]
    assert missing == []


def test_every_route_but_health_and_sign_in_returns_401_without_a_session(app):
    from api.policy import POLICY
    anon = _client(app)
    leaks = []
    for method, path in _routes(app):
        if POLICY[(method, path)] == "public":
            continue
        r = anon.request(method, _concrete(path), json={})
        if r.status_code != 401:
            leaks.append((method, path, r.status_code))
    assert leaks == []


def test_public_routes_are_only_health_and_sign_in(app):
    from api.policy import POLICY
    public = {k for k, v in POLICY.items() if v == "public"}
    assert all(p == "/api/health" or p.startswith("/api/auth/") or p == "/{path:path}" for _, p in public), public


def test_state_changing_requests_need_the_csrf_header(app, admin):
    no_header = TestClient(app)
    no_header.cookies.set("fmea_session", admin.cookies.get("fmea_session"))
    assert no_header.get("/api/portfolios").status_code == 200
    assert no_header.post("/api/portfolios", json={"name": "P"}).status_code == 403


# ── roles ─────────────────────────────────────────────────────────────────────

def test_denied_roles_get_403_on_every_route_they_may_not_use(app, admin):
    from api.policy import POLICY, ROLE_PERMISSIONS
    clients = {role: _user(admin, f"u-{role}", role) for role in ROLE_PERMISSIONS if role != "admin"}
    wrong = []
    for (method, path), perm in POLICY.items():
        if perm == "public":
            continue
        for role, c in clients.items():
            allowed = perm in ROLE_PERMISSIONS[role]
            if allowed:
                continue
            code = c.request(method, _concrete(path), json={}).status_code
            if code != 403:
                wrong.append((role, method, path, code))
    assert wrong == []


def test_developer_cannot_apply_a_score_change_or_set_a_key(app, admin):
    dev = _user(admin, "dana", "developer")
    body = {"workspace_id": 1, "failure_mode": "x", "new_s": 5, "new_o": 5, "new_d": 5, "justification": "because"}
    assert dev.post("/api/scoring/adjustment", json=body).status_code == 403
    assert dev.put("/api/settings/providers/openai/key", json={"api_key": "k"}).status_code == 403
    assert dev.post("/api/chat/proposals/1/apply").status_code == 403
    assert dev.get("/api/settings/providers").status_code == 200                       # reading is allowed


def test_security_engineer_may_adjust_scores_and_admin_may_set_keys(app, admin, monkeypatch):
    import core.providers as providers
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "valid")
    se = _user(admin, "sam", "security_engineer")
    ws = db.upsert_workspace(SimpleNamespace(customer="c", project="p", function="", business_tier="Tier 1",
                                             user_type="external_customers", business_context=""))
    body = {"workspace_id": ws, "failure_mode": "x", "new_s": 5, "new_o": 5, "new_d": 5, "justification": "because"}
    assert se.post("/api/scoring/adjustment", json=body).status_code == 201
    assert se.put("/api/settings/providers/openai/key", json={"api_key": "k"}).status_code == 403
    assert admin.put("/api/settings/providers/openai/key", json={"api_key": "sk-x-1234"}).status_code == 200


def test_only_admins_manage_users(app, admin):
    se = _user(admin, "sam", "security_engineer")
    assert se.get("/api/users").status_code == 403
    assert se.post("/api/users", json={"username": "z", "password": PASSWORD, "role": "viewer"}).status_code == 403


# ── audit: the signed-in user is recorded ─────────────────────────────────────

def _workspace():
    return db.upsert_workspace(SimpleNamespace(customer="c", project="p", function="", business_tier="Tier 1",
                                               user_type="external_customers", business_context=""))


def test_adjustment_records_the_signed_in_user(app, admin):
    se = _user(admin, "sam", "security_engineer")
    ws = _workspace()
    body = {"workspace_id": ws, "failure_mode": "x", "new_s": 5, "new_o": 5, "new_d": 5, "justification": "because"}
    created = se.post("/api/scoring/adjustment", json=body).json()
    assert created["adjusted_by"] == "sam"
    assert admin.get(f"/api/scoring/adjustments/{ws}").json()[0]["adjusted_by"] == "sam"


def test_applied_chat_proposal_records_the_signed_in_user(app, admin):
    se = _user(admin, "sam", "security_engineer")
    ws = _workspace()
    db.save_scan_snapshot(ws, None, "fp", {"failures": [{"failure_mode": "SQL injection"}], "risks": []}, {"a.py": "x"})
    thread = db.get_or_create_chat_thread(ws)
    snap = db.get_latest_snapshot(ws)
    pid = db.create_proposal(thread["id"], snap["id"], "score_adjustment", "SQL injection",
                             {"severity": 7, "occurrence": 5, "detection": 5}, "evidence shows it")
    r = se.post(f"/api/chat/proposals/{pid}/apply")
    assert r.status_code == 200, r.text
    assert r.json()["proposal"]["decided_by"] == "sam"
    assert se.get(f"/api/scoring/adjustments/{ws}").json()[0]["adjusted_by"] == "sam"


# ── server-side results ───────────────────────────────────────────────────────

def test_a_scan_saved_by_one_user_is_readable_by_another(app, admin):
    portfolio = admin.post("/api/portfolios", json={"name": "Shop"}).json()
    project = admin.post(f"/api/portfolios/{portfolio['id']}/projects",
                         json={"name": "api", "repo_url": "https://github.com/o/r"}).json()
    ws = db.upsert_workspace(SimpleNamespace(customer="Shop", project="api", function="", business_tier="Tier 1",
                                             user_type="external_customers", business_context=""))
    result = {"risks": [{"failure_mode": "x", "severity": 9, "occurrence": 5, "detection": 5, "rpn": 225}],
              "failures": [{"failure_mode": "x"}], "workspace_id": ws, "fingerprint": "f1", "from_cache": False}
    db.save_scan_snapshot(ws, 3, "f1", result, {})
    viewer = _user(admin, "vic", "viewer")
    r = viewer.get(f"/api/projects/{project['id']}/latest-scan")
    assert r.status_code == 200
    body = r.json()
    assert body["workspace_id"] == ws and body["risk_count"] == 1 and body["max_rpn"] == 225
    assert body["result"]["risks"][0]["failure_mode"] == "x" and body["repoUrl"] == "https://github.com/o/r"
    empty = admin.post(f"/api/portfolios/{portfolio['id']}/projects", json={"name": "web"}).json()
    assert viewer.get(f"/api/projects/{empty['id']}/latest-scan").status_code == 404
    assert viewer.get("/api/projects/9999/latest-scan").status_code == 404


# ── migration of an existing database ─────────────────────────────────────────

def test_existing_database_loads_after_migration(app, tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.executescript("""
        CREATE TABLE workspaces (id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT NOT NULL, project TEXT NOT NULL,
            function TEXT, business_tier TEXT, user_type TEXT, business_context TEXT, customer_learning INTEGER DEFAULT 1,
            created_at TEXT NOT NULL, UNIQUE(customer, project));
        CREATE TABLE adjustments (id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL, failure_mode TEXT NOT NULL,
            new_s INTEGER NOT NULL, new_o INTEGER NOT NULL, new_d INTEGER NOT NULL, new_rpn INTEGER NOT NULL,
            justification TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE chat_threads (id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL UNIQUE, summary TEXT, created_at TEXT NOT NULL);
        CREATE TABLE chat_proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER NOT NULL, message_id INTEGER,
            snapshot_id INTEGER, kind TEXT NOT NULL, failure_mode TEXT NOT NULL, payload_json TEXT NOT NULL, reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed', result_json TEXT, created_at TEXT NOT NULL, decided_at TEXT);
    """)
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO workspaces (customer, project, created_at) VALUES ('Old', 'Proj', ?)", (now,))
    conn.execute("INSERT INTO adjustments (workspace_id, failure_mode, new_s, new_o, new_d, new_rpn, justification, created_at)"
                 " VALUES (1, 'legacy', 5, 5, 5, 125, 'old row', ?)", (now,))
    conn.commit(); conn.close()
    monkeypatch.setattr(db, "_DB_PATH", old)

    rows = db.get_adjustments(1)
    assert rows[0]["failure_mode"] == "legacy" and rows[0]["adjusted_by"] is None
    admin = _client(app)
    assert admin.post("/api/auth/setup", json={"username": "root", "password": PASSWORD}).status_code == 201
    assert db.workspace_exists(1)
    assert admin.get("/api/scoring/adjustments/1").json()[0]["failure_mode"] == "legacy"


def test_environment_bootstrap_creates_the_first_admin(app, monkeypatch):
    from core import auth
    monkeypatch.setenv("FMEA_ADMIN_USER", "boot")
    monkeypatch.setenv("FMEA_ADMIN_PASSWORD", PASSWORD)
    auth.bootstrap_admin_from_env()
    c = _client(app)
    assert c.post("/api/auth/login", json={"username": "boot", "password": PASSWORD}).status_code == 200
    auth.bootstrap_admin_from_env()                                   # idempotent
    assert len(c.get("/api/users").json()) == 1


def test_demo_mode_flag_is_reported_and_does_not_bypass_sign_in(app, monkeypatch):
    monkeypatch.setenv("FMEA_DEMO_MODE", "1")
    c = _client(app)
    assert c.get("/api/auth/status").json()["demo_mode"] is True
    assert c.get("/api/portfolios").status_code == 401


# ── review follow-ups ─────────────────────────────────────────────────────────

def test_throttle_cannot_be_bypassed_with_whitespace_or_case(app, admin):
    c = _client(app)
    for name in ["root", "root ", " ROOT", "Root  ", "root", "ROOT "]:
        c.post("/api/auth/login", json={"username": name, "password": "bad-password-00"})
    assert c.post("/api/auth/login", json={"username": "  rOOt", "password": PASSWORD}).status_code == 429


def test_one_client_cannot_lock_a_user_out_for_everyone(app, admin):
    from core import auth
    for _ in range(5):
        assert auth.authenticate("root", "bad-password-00", client="10.0.0.1") is None
    with pytest.raises(auth.AuthError):
        auth.authenticate("root", PASSWORD, client="10.0.0.1")
    assert auth.authenticate("root", PASSWORD, client="10.0.0.2")["username"] == "root"


def test_failure_table_is_bounded(app, monkeypatch):
    from core import auth
    monkeypatch.setattr(auth, "MAX_TRACKED", 20)
    monkeypatch.setattr(auth, "verify_password", lambda password, stored: False)      # skip the slow hash
    for i in range(auth.MAX_TRACKED + 50):
        auth.authenticate(f"spray-{i}", "x", client="9.9.9.9")
    assert len(auth._failures) <= auth.MAX_TRACKED


def test_sso_users_do_not_close_setup(app):
    from core import auth
    auth.create_user("sso-person", None, "viewer", oidc_subject="sub-1")
    assert _client(app).get("/api/auth/status").json()["setup_required"] is True
    assert _client(app).post("/api/auth/setup", json={"username": "root", "password": PASSWORD}).status_code == 201


def test_setup_token_is_required_when_configured(app, monkeypatch):
    monkeypatch.setenv("FMEA_SETUP_TOKEN", "let-me-in-please")
    c = _client(app)
    assert c.get("/api/auth/status").json()["setup_token_required"] is True
    assert c.post("/api/auth/setup", json={"username": "root", "password": PASSWORD}).status_code == 403
    assert c.post("/api/auth/setup", json={"username": "root", "password": PASSWORD, "setup_token": "wrong"}).status_code == 403
    ok = c.post("/api/auth/setup", json={"username": "root", "password": PASSWORD, "setup_token": "let-me-in-please"})
    assert ok.status_code == 201


def test_api_docs_and_schema_are_not_public(app):
    c = _client(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404, path


def test_no_unlisted_route_exists_at_all(app):
    from starlette.routing import Route
    from api.policy import POLICY
    extra = [r.path for r in app.routes if not isinstance(r, APIRoute) and getattr(r, "path", None) not in ("/assets",)]
    assert extra == [], extra
    assert all((m, p) in POLICY for m, p in _routes(app))


def test_session_cookie_is_secure_by_default_and_can_be_relaxed_for_local_http(app, admin, monkeypatch):
    monkeypatch.delenv("FMEA_COOKIE_SECURE")
    r = _client(app).post("/api/auth/login", json={"username": "root", "password": PASSWORD})
    assert "secure" in r.headers["set-cookie"].lower()
    monkeypatch.setenv("FMEA_COOKIE_SECURE", "0")
    r = _client(app).post("/api/auth/login", json={"username": "root", "password": PASSWORD})
    assert "secure" not in r.headers["set-cookie"].lower()


def test_key_changes_and_user_changes_are_audited_without_secrets(app, admin, monkeypatch):
    import core.providers as providers
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "valid")
    admin.put("/api/settings/providers/openai/key", json={"api_key": "sk-super-secret-9999"})
    admin.delete("/api/settings/providers/openai/key")
    _user(admin, "dana", "developer")
    conn = sqlite3.connect(db._DB_PATH)
    rows = conn.execute("SELECT username, action, detail FROM audit_events ORDER BY id").fetchall()
    conn.close()
    actions = [(u, a) for u, a, _ in rows]
    assert ("root", "provider_key_set") in actions and ("root", "provider_key_removed") in actions
    assert ("root", "user_created") in actions and ("dana", "sign_in") in actions
    assert "secret" not in str(rows)


def test_roles_and_passwords_of_sso_users_belong_to_the_identity_provider(app, admin):
    from core import auth
    sso = auth.create_user("sso-person", None, "viewer", oidc_subject="sub-9")
    assert admin.patch(f"/api/users/{sso['id']}", json={"role": "admin"}).status_code == 409
    assert admin.patch(f"/api/users/{sso['id']}", json={"password": PASSWORD}).status_code == 409
    assert admin.patch(f"/api/users/{sso['id']}", json={"disabled": True}).status_code == 200      # disabling stays local
    assert auth.authenticate("sso-person", PASSWORD) is None                                       # no password login


def test_an_unknown_role_value_in_the_database_is_refused_not_a_500(app, admin):
    other = _user(admin, "odd", "viewer")
    conn = db.get_db(); conn.execute("UPDATE users SET role='mystery' WHERE username='odd'"); conn.commit(); conn.close()
    assert other.get("/api/portfolios").status_code == 403
