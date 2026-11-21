"""
B-042 — deployment model and container packaging (ADR-026).

  AC: provider keys are not readable in plain text on disk
  AC: stored scan sources are deleted after the configured retention, and on request per project
  AC: two scans run concurrently with correct, separate call counts
  AC: /api/health reports version and database status
  plus: data directory on a volume, built frontend served by the API, container files
"""

import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import core.llm as llm
import core.providers as providers
import core.settings as settings
import memory.db as db

ROOT = Path(__file__).resolve().parent.parent
SECRET = "mJ1v0m2n4o6q8s0u2w4y6A8C0E2G4I6K8M0O2Q4S6U8="   # a valid Fernet key (tests only)
PLAIN = "sk-test-plain-key-12345"


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    for p in providers.PROVIDERS.values():
        monkeypatch.delenv(p["env_var"], raising=False)
    return tmp_path / "settings.json"


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fmea.db")
    return tmp_path / "fmea.db"


# ── data directory on a volume ────────────────────────────────────────────────

def _paths_in_subprocess(env_extra: dict) -> dict:
    import os
    code = (
        "import json, core.settings as s, memory.db as d, core.workspace as w, memory.workspace_store as ws,"
        " memory.eval_store as e, memory.analysis_cache as a, memory.learning_memory as l\n"
        "print(json.dumps({'settings': str(s._SETTINGS_PATH), 'db': str(d._DB_PATH),"
        " 'workspaces': str(w._MEMORY_ROOT), 'store': str(ws._MEMORY_ROOT), 'eval': str(e._MEMORY_ROOT),"
        " 'cache': str(a.CACHE_PATH), 'learning': str(l.LEARNING_PATH)}))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "FMEA_DATA_DIR"} | env_extra
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-1500:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_data_dir_env_moves_every_runtime_file(tmp_path):
    paths = _paths_in_subprocess({"FMEA_DATA_DIR": str(tmp_path)})
    assert all(Path(p).is_relative_to(tmp_path) for p in paths.values()), paths


def test_default_locations_are_unchanged_without_data_dir():
    paths = _paths_in_subprocess({})
    assert Path(paths["db"]) == ROOT / "memory" / "fmea.db"
    assert Path(paths["settings"]) == ROOT / "core" / "settings.json"


# ── provider keys encrypted at rest ───────────────────────────────────────────

def test_key_is_not_readable_on_disk_but_round_trips(tmp_settings, monkeypatch):
    monkeypatch.setenv("FMEA_SECRET_KEY", SECRET)
    providers.set_api_key("openai", PLAIN)
    raw = tmp_settings.read_text(encoding="utf-8")
    assert PLAIN not in raw and "12345" not in raw
    assert providers.get_api_key("openai") == PLAIN


def test_wrong_secret_key_reads_as_no_key_instead_of_crashing(tmp_settings, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FMEA_SECRET_KEY", SECRET)
    providers.set_api_key("openai", PLAIN)
    monkeypatch.setenv("FMEA_SECRET_KEY", Fernet.generate_key().decode())
    assert providers.get_api_key("openai") is None


def test_existing_plaintext_keys_are_encrypted_on_startup(tmp_settings, monkeypatch):
    settings.set_setting("api_keys", {"openai": PLAIN})           # saved before a secret key existed
    monkeypatch.setenv("FMEA_SECRET_KEY", SECRET)
    from core.secrets import encrypt_stored_keys
    encrypt_stored_keys()
    assert PLAIN not in tmp_settings.read_text(encoding="utf-8")
    assert providers.get_api_key("openai") == PLAIN


def test_without_secret_key_keys_stay_plaintext_and_health_says_so(tmp_settings, monkeypatch, client):
    monkeypatch.delenv("FMEA_SECRET_KEY", raising=False)
    providers.set_api_key("openai", PLAIN)
    assert PLAIN in tmp_settings.read_text(encoding="utf-8")
    assert client.get("/api/health").json()["key_storage"] == "plaintext"


def test_invalid_secret_key_is_reported_not_silently_ignored(monkeypatch):
    from core.secrets import SecretKeyError, cipher
    monkeypatch.setenv("FMEA_SECRET_KEY", "not-a-fernet-key")
    with pytest.raises(SecretKeyError):
        cipher()


def test_api_never_returns_the_stored_key(tmp_settings, monkeypatch, client):
    monkeypatch.setenv("FMEA_SECRET_KEY", SECRET)
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "valid")
    client.put("/api/settings/providers/openai/key", json={"api_key": PLAIN})
    assert PLAIN not in client.get("/api/settings/providers").text


# ── per-scan state: two scans at once ─────────────────────────────────────────

class _Resp:
    def __init__(self, p, c):
        self.usage = SimpleNamespace(prompt_tokens=p, completion_tokens=c)
        self.choices = [SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")]


class _FakeClient:
    def __init__(self, barrier):
        self.barrier = barrier
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.barrier.wait(timeout=5)          # both scans are inside a call at the same moment
        return _Resp(100, 10)


def test_two_concurrent_scans_keep_separate_call_counts(tmp_settings, monkeypatch):
    barrier = threading.Barrier(2)
    monkeypatch.setattr(llm, "_get_client", lambda provider_id: _FakeClient(barrier))
    results = {}

    def scan(name, calls):
        llm.reset_call_count()
        for _ in range(calls):
            llm.call_llm("hello", max_tokens=100)
        results[name] = (llm.get_call_count(), llm.get_token_usage())

    # equal call counts keep the barrier in step; token totals must still be per scan
    ta = threading.Thread(target=scan, args=("a", 3))
    tb = threading.Thread(target=scan, args=("b", 3))
    ta.start(); tb.start(); ta.join(10); tb.join(10)
    assert results["a"] == (3, (300, 30))
    assert results["b"] == (3, (300, 30))


def test_a_scan_does_not_see_another_threads_calls(tmp_settings, monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda provider_id: _FakeClient(threading.Barrier(1)))
    llm.reset_call_count()
    t = threading.Thread(target=lambda: (llm.reset_call_count(), llm.call_llm("x", max_tokens=100)))
    t.start(); t.join(10)
    assert llm.get_call_count() == 0 and llm.get_token_usage() == (0, 0)


# ── retention of scanned source ───────────────────────────────────────────────

def _snapshot(ws_id, fingerprint, files, age_days=0):
    snap_id = db.save_scan_snapshot(ws_id, None, fingerprint, {"risks": []}, files)
    when = (datetime.now() - timedelta(days=age_days)).isoformat()
    conn = db.get_db()
    conn.execute("UPDATE scan_snapshots SET created_at=? WHERE id=?", (when, snap_id))
    conn.commit(); conn.close()
    return snap_id


@pytest.fixture
def ws_id(tmp_db):
    ws = SimpleNamespace(customer="c", project="p", function="", business_tier="Tier 1",
                         user_type="external_customers", business_context="")
    return db.upsert_workspace(ws)


def test_purge_deletes_only_sources_older_than_retention(ws_id):
    old = _snapshot(ws_id, "old", {"a.py": "secret code"}, age_days=40)
    new = _snapshot(ws_id, "new", {"b.py": "recent code"}, age_days=1)
    deleted = db.purge_expired_sources(30)
    assert deleted == 1
    assert db.get_snapshot_files(old) == {}
    assert db.get_snapshot_files(new) == {"b.py": "recent code"}
    assert db.get_latest_snapshot(ws_id) is not None          # findings are kept


def test_delete_sources_on_request_for_one_project(client, ws_id, tmp_db):
    snap = _snapshot(ws_id, "f1", {"a.py": "code"})
    r = client.delete(f"/api/workspace/{ws_id}/sources")
    assert r.status_code == 200 and r.json()["files_deleted"] == 1
    assert db.get_snapshot_files(snap) == {}
    assert client.delete("/api/workspace/99999/sources").status_code == 404


def test_zero_retention_stores_no_source(ws_id, monkeypatch):
    from core.chat import persist_scan_for_chat
    monkeypatch.setenv("FMEA_SOURCE_RETENTION_DAYS", "0")
    snap = persist_scan_for_chat({"workspace_id": ws_id, "fingerprint": "z"}, "x = 1", None)
    assert snap is not None and db.get_snapshot_files(snap) == {}


def test_retention_days_default_env_and_setting(tmp_settings, monkeypatch):
    from core.retention import retention_days
    monkeypatch.delenv("FMEA_SOURCE_RETENTION_DAYS", raising=False)
    assert retention_days() == 30
    settings.set_setting("source_retention_days", 7)
    assert retention_days() == 7
    monkeypatch.setenv("FMEA_SOURCE_RETENTION_DAYS", "3")
    assert retention_days() == 3
    monkeypatch.setenv("FMEA_SOURCE_RETENTION_DAYS", "junk")
    assert retention_days() == 7                                # bad env value falls back


# ── health ────────────────────────────────────────────────────────────────────

def test_health_reports_version_and_database_status(client, tmp_db):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok" and body["version"]


def test_health_reports_database_failure_with_503(client, monkeypatch):
    def broken():
        raise RuntimeError("disk gone")
    monkeypatch.setattr(db, "get_db", broken)
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["database"] == "error"
    assert "disk gone" not in r.text


# ── built frontend served by the API ──────────────────────────────────────────

def test_built_frontend_is_served_and_api_routes_still_win(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "x.js").write_text("1", encoding="utf-8")
    monkeypatch.setenv("FMEA_STATIC_DIR", str(tmp_path))
    import importlib, api.main as main
    app = importlib.reload(main).app
    try:
        c = TestClient(app)
        assert c.get("/").text == "<html>app</html>"
        assert c.get("/some/client/route").text == "<html>app</html>"
        assert c.get("/assets/x.js").text == "1"
        assert c.get("/api/health").json()["status"] == "ok"
        assert c.get("/api/does-not-exist").status_code == 404      # not swallowed by the SPA fallback
    finally:
        monkeypatch.delenv("FMEA_STATIC_DIR")
        importlib.reload(main)


# ── container files ───────────────────────────────────────────────────────────

def test_container_files_follow_the_adr():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "USER " in docker and "USER root" not in docker      # non-root
    assert "npm run build" in docker                             # frontend built into the image
    assert "FMEA_DATA_DIR" in docker
    assert "127.0.0.1:8000:8000" in compose                      # not exposed until sign-in exists (B-015)
    assert "FMEA_SECRET_KEY" in compose and ":?" in compose      # compose refuses to start without it
    assert "volumes:" in compose
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for must in ("memory/fmea.db", "core/settings.json", ".env", "node_modules"):
        assert must in ignore


# ── review follow-ups ─────────────────────────────────────────────────────────

def test_usage_follows_the_context_into_to_thread_style_workers(tmp_settings, monkeypatch):
    import contextvars
    monkeypatch.setattr(llm, "_get_client", lambda provider_id: _FakeClient(threading.Barrier(1)))
    llm.reset_call_count()
    ctx = contextvars.copy_context()
    t = threading.Thread(target=lambda: ctx.run(lambda: llm.call_llm("x", max_tokens=100)))
    t.start(); t.join(10)
    assert llm.get_call_count() == 1                      # the worker added to this scan's counters


def test_zero_retention_scan_does_not_wipe_other_projects(ws_id, monkeypatch):
    from core.chat import persist_scan_for_chat
    other = _snapshot(ws_id, "keep", {"a.py": "kept"})
    monkeypatch.setenv("FMEA_SOURCE_RETENTION_DAYS", "0")
    persist_scan_for_chat({"workspace_id": ws_id, "fingerprint": "new"}, "x = 1", None)
    assert db.get_snapshot_files(other) == {"a.py": "kept"}


def test_purge_now_uses_the_configured_retention(ws_id, monkeypatch):
    from core.retention import purge_now
    monkeypatch.setenv("FMEA_SOURCE_RETENTION_DAYS", "30")
    old = _snapshot(ws_id, "old2", {"a.py": "x"}, age_days=45)
    assert purge_now() == 1 and db.get_snapshot_files(old) == {}


def test_health_and_providers_flag_keys_that_cannot_be_decrypted(tmp_settings, monkeypatch, client):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FMEA_SECRET_KEY", SECRET)
    providers.set_api_key("openai", PLAIN)
    monkeypatch.setenv("FMEA_SECRET_KEY", Fernet.generate_key().decode())
    assert client.get("/api/health").json()["undecryptable_keys"] == ["openai"]
    openai_row = next(p for p in client.get("/api/settings/providers").json() if p["id"] == "openai")
    assert openai_row["key_set"] is False and openai_row["source"] is None


def test_odd_static_paths_fall_back_to_the_app_shell(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("shell", encoding="utf-8")
    monkeypatch.setenv("FMEA_STATIC_DIR", str(tmp_path))
    import importlib, api.main as main
    try:
        c = TestClient(importlib.reload(main).app)
        assert c.get("/a%00b").status_code == 200
        assert c.get("/..%2f..%2fetc/passwd").text == "shell"
    finally:
        monkeypatch.delenv("FMEA_STATIC_DIR")
        importlib.reload(main)
