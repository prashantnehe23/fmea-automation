"""
B-043 — private repository access (ADR-027 point 9, amended: credentials are per GitHub owner).

  AC: a private repository is scanned end to end with a stored credential
  AC: missing or revoked access gives a plain message naming the repository and the fix
  AC: the credential never appears in prompts, logs, telemetry or API responses
  AC: public repositories still scan without a credential
"""

import email.message
import json
import logging
import sqlite3
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import core.github_fetcher as fetcher
import core.providers as providers
import core.settings as settings
import memory.db as db
from core import repo_credentials

TOKEN = "github_pat_CANARY_do_not_leak_0123456789"
SECRET = "mJ1v0m2n4o6q8s0u2w4y6A8C0E2G4I6K8M0O2Q4S6U8="
PRIVATE_URL, PUBLIC_URL = "https://github.com/acme/private-repo", "https://github.com/o/public"
TREE = {"tree": [{"type": "blob", "path": "app.py", "size": 20}, {"type": "blob", "path": "README.md", "size": 20}]}


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(url, code, headers=None):
    msg = email.message.Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError(url, code, "x", msg, None)


class FakeGitHub:
    """Stands in for github.com: the private repository answers only to the right bearer token."""

    def __init__(self, revoked=False, rate_limited=False, token_without_access=False):
        self.calls, self.revoked, self.rate_limited, self.no_access = [], revoked, rate_limited, token_without_access

    def __call__(self, req, timeout=None):
        url, auth = req.full_url, req.get_header("Authorization")
        self.calls.append((url, auth, req.get_header("Accept")))
        if self.rate_limited and "acme/private-repo" in url:
            raise http_error(url, 403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790000000"})
        if url.endswith("/user"):
            if auth == f"Bearer {TOKEN}":
                return FakeResponse(b'{"login": "someone"}')
            raise http_error(url, 401)
        if "acme/private-repo" in url:
            if auth and self.revoked:
                raise http_error(url, 401)
            if auth == f"Bearer {TOKEN}" and not self.no_access:
                return FakeResponse(json.dumps(TREE).encode() if "/git/trees/" in url else b"x = 1\n")
            raise http_error(url, 404)
        if "o/public" in url:
            assert auth is None, "a public repository must not be sent a credential"
            return FakeResponse(json.dumps(TREE).encode() if "/git/trees/" in url else b"x = 1\n")
        raise http_error(url, 404)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fmea.db")
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setenv("FMEA_SECRET_KEY", SECRET)
    for p in providers.PROVIDERS.values():
        monkeypatch.delenv(p["env_var"], raising=False)
    return tmp_path


def install(monkeypatch, **kw):
    fake = FakeGitHub(**kw)
    monkeypatch.setattr(fetcher, "_urlopen", fake)
    monkeypatch.setattr(urllib.request, "urlopen", fake)          # the token check uses urlopen directly
    return fake


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app, headers={"X-Requested-With": "fmea"})


def scan_events(client, url, **extra):
    with client.stream("POST", "/api/github/scan", json={"repo_url": url, **extra}) as r:
        body = "".join(r.iter_text())
    events = []
    for frame in body.strip().split("\n\n"):
        data = [l[6:] for l in frame.splitlines() if l.startswith("data: ")]
        if data:
            events.append(json.loads(data[0]))
    return body, events


# ── credential store ──────────────────────────────────────────────────────────

def test_credentials_are_encrypted_at_rest_and_listed_masked(env):
    repo_credentials.set_token("Acme", TOKEN)
    raw = (env / "settings.json").read_text(encoding="utf-8")
    assert TOKEN not in raw and "CANARY" not in raw
    assert repo_credentials.token_for("acme") == TOKEN
    assert repo_credentials.token_for("ACME") == TOKEN                      # owners are case-insensitive
    listed = repo_credentials.list_credentials()
    assert listed == [{"provider": "github", "owner": "acme", "hint": "••••6789"}]


def test_owner_specific_credential_wins_over_the_catch_all(env):
    repo_credentials.set_token("*", "github_pat_catchall_1111")
    repo_credentials.set_token("acme", TOKEN)
    assert repo_credentials.token_for("acme") == TOKEN
    assert repo_credentials.token_for("other") == "github_pat_catchall_1111"
    repo_credentials.remove("acme")
    assert repo_credentials.token_for("acme") == "github_pat_catchall_1111"
    repo_credentials.remove("*")
    assert repo_credentials.token_for("acme") is None


def test_an_undecryptable_credential_reads_as_none(env, monkeypatch):
    from cryptography.fernet import Fernet
    repo_credentials.set_token("acme", TOKEN)
    monkeypatch.setenv("FMEA_SECRET_KEY", Fernet.generate_key().decode())
    assert repo_credentials.token_for("acme") is None


# ── fetcher ───────────────────────────────────────────────────────────────────

def test_stored_credential_is_sent_as_a_bearer_token_and_files_come_from_the_contents_api(env, monkeypatch):
    repo_credentials.set_token("acme", TOKEN)
    fake = install(monkeypatch)
    ref, paths, _ = fetcher.scan_repo(PRIVATE_URL)
    text = fetcher.fetch_file_content(ref.owner, ref.repo, ref.branch, "app.py")
    assert paths == ["README.md", "app.py"] or sorted(paths) == ["README.md", "app.py"] or "app.py" in paths
    assert text == "x = 1\n"
    assert all(auth == f"Bearer {TOKEN}" for _, auth, _ in fake.calls)
    content_call = next(c for c in fake.calls if "/contents/app.py" in c[0])
    assert "ref=main" in content_call[0] and content_call[2] == "application/vnd.github.raw+json"


def test_public_repositories_are_fetched_without_any_credential(env, monkeypatch):
    repo_credentials.set_token("acme", TOKEN)                                # a credential for another owner exists
    fake = install(monkeypatch)
    ref, paths, _ = fetcher.scan_repo(PUBLIC_URL)
    assert fetcher.fetch_file_content(ref.owner, ref.repo, ref.branch, "app.py") == "x = 1\n"
    assert all(auth is None for _, auth, _ in fake.calls)
    assert any(url.startswith("https://raw.githubusercontent.com/o/public/") for url, _, _ in fake.calls)


def test_private_repository_without_a_credential_says_what_to_do(env, monkeypatch):
    install(monkeypatch)
    with pytest.raises(fetcher.RepoAccessError) as exc:
        fetcher.scan_repo(PRIVATE_URL)
    e = exc.value
    assert e.code == "not_found" and "acme/private-repo" in e.message
    assert "Settings" in e.message and "acme" in e.message and "private" in e.message


def test_revoked_credential_names_the_owner_and_the_fix(env, monkeypatch):
    repo_credentials.set_token("acme", TOKEN)
    install(monkeypatch, revoked=True)
    with pytest.raises(fetcher.RepoAccessError) as exc:
        fetcher.scan_repo(PRIVATE_URL)
    assert exc.value.code == "token_rejected" and "acme" in exc.value.message and "Settings" in exc.value.message
    assert TOKEN not in exc.value.message


def test_credential_without_access_to_the_repository_says_so(env, monkeypatch):
    repo_credentials.set_token("acme", TOKEN)
    install(monkeypatch, token_without_access=True)
    with pytest.raises(fetcher.RepoAccessError) as exc:
        fetcher.scan_repo(PRIVATE_URL)
    assert exc.value.code == "no_access" and "acme/private-repo" in exc.value.message
    assert "Contents" in exc.value.message                                   # the permission to grant


def test_rate_limit_is_explained_with_the_reset_time(env, monkeypatch):
    install(monkeypatch, rate_limited=True)
    with pytest.raises(fetcher.RepoAccessError) as exc:
        fetcher.scan_repo(PRIVATE_URL)
    assert exc.value.code == "rate_limited" and "token" in exc.value.message.lower()


def test_an_unknown_branch_on_a_public_repository_keeps_the_branch_hint(env, monkeypatch):
    install(monkeypatch)
    with pytest.raises(Exception) as exc:
        fetcher.scan_repo("https://github.com/o/nothing-here")
    assert "main" in str(exc.value) and "master" in str(exc.value)


# ── scan endpoint ─────────────────────────────────────────────────────────────

def stub_pipeline(monkeypatch):
    import api.routers.github as gh
    monkeypatch.setattr(gh, "run_fmea", lambda code, **kw: {"failures": [], "risks": [], "fingerprint": "f"})


def test_private_repository_is_scanned_end_to_end_with_the_credential(env, client, monkeypatch):
    repo_credentials.set_token("acme", TOKEN)
    install(monkeypatch)
    stub_pipeline(monkeypatch)
    _, events = scan_events(client, PRIVATE_URL)
    done = next(e for e in events if e["stage"] == "complete")
    assert done["repo"]["owner"] == "acme" and done["repo"]["files_scanned"] >= 1


def test_public_repository_still_scans_without_a_credential(env, client, monkeypatch):
    install(monkeypatch)
    stub_pipeline(monkeypatch)
    _, events = scan_events(client, PUBLIC_URL)
    assert any(e["stage"] == "complete" for e in events)


def test_missing_access_reaches_the_user_as_a_plain_event_with_a_settings_action(env, client, monkeypatch):
    install(monkeypatch)
    _, events = scan_events(client, PRIVATE_URL)
    err = next(e for e in events if e["stage"] == "error")
    assert err["code"] == "not_found" and err["action"] == "open_settings"
    assert "acme/private-repo" in err["msg"] and "HTTP Error" not in err["msg"]


def test_preview_explains_missing_access_too(env, client, monkeypatch):
    install(monkeypatch)
    r = client.post("/api/github/preview", json={"repo_url": PRIVATE_URL})
    assert r.status_code == 400 and "acme/private-repo" in r.json()["detail"] and "HTTP Error" not in r.json()["detail"]


# ── credential API ────────────────────────────────────────────────────────────

def test_saving_a_credential_validates_it_and_never_echoes_it(env, client, monkeypatch):
    install(monkeypatch)
    bad = client.put("/api/settings/repo-credentials", json={"owner": "acme", "token": "github_pat_wrong_0000"})
    assert bad.status_code == 422 and "rejected" in bad.json()["detail"] and "wrong" not in bad.json()["detail"]
    assert client.get("/api/settings/repo-credentials").json() == []
    ok = client.put("/api/settings/repo-credentials", json={"owner": "Acme", "token": TOKEN})
    assert ok.status_code == 200 and TOKEN not in ok.text
    assert TOKEN not in client.get("/api/settings/repo-credentials").text
    assert client.get("/api/settings/repo-credentials").json()[0]["owner"] == "acme"
    assert client.delete("/api/settings/repo-credentials", params={"owner": "acme"}).status_code == 200
    assert client.get("/api/settings/repo-credentials").json() == []


def test_unverifiable_credential_is_saved_with_a_warning_status(env, client, monkeypatch):
    def offline(req, timeout=None):
        raise urllib.error.URLError("no network")
    monkeypatch.setattr(urllib.request, "urlopen", offline)
    r = client.put("/api/settings/repo-credentials", json={"owner": "acme", "token": TOKEN})
    assert r.status_code == 200 and r.json()["status"] == "unverified"


def test_credential_changes_are_audited_without_the_token_and_limited_to_admins(env, real_auth, monkeypatch):
    from api.main import app
    monkeypatch.setenv("FMEA_COOKIE_SECURE", "0")
    install(monkeypatch)
    admin = TestClient(app, headers={"X-Requested-With": "fmea"})
    admin.post("/api/auth/setup", json={"username": "root", "password": "correct-horse-battery"})
    admin.put("/api/settings/repo-credentials", json={"owner": "acme", "token": TOKEN})
    admin.post("/api/users", json={"username": "dana", "password": "correct-horse-battery", "role": "developer"})
    dev = TestClient(app, headers={"X-Requested-With": "fmea"})
    dev.post("/api/auth/login", json={"username": "dana", "password": "correct-horse-battery"})
    assert dev.put("/api/settings/repo-credentials", json={"owner": "x", "token": TOKEN}).status_code == 403
    assert dev.get("/api/settings/repo-credentials").status_code == 403
    conn = sqlite3.connect(db._DB_PATH)
    rows = conn.execute("SELECT username, action, detail FROM audit_events WHERE action LIKE 'repo_credential%'").fetchall()
    conn.close()
    assert rows == [("root", "repo_credential_set", "github acme")]


# ── the credential never leaks ────────────────────────────────────────────────

class RecordingClient:
    def __init__(self, sink):
        self.sink = sink
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.sink.append(json.dumps(kw.get("messages"), default=str))
        return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                               choices=[SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")])


def test_credential_never_appears_in_prompts_logs_telemetry_or_responses(env, client, monkeypatch, caplog):
    import core.llm as llm
    caplog.set_level(logging.DEBUG)
    settings.set_setting("api_keys", {"openai": "sk-test-not-real"})
    repo_credentials.set_token("acme", TOKEN)
    fake = install(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(llm, "_get_client", lambda provider_id: RecordingClient(prompts))

    responses = [
        client.put("/api/settings/repo-credentials", json={"owner": "acme", "token": TOKEN}).text,
        client.get("/api/settings/repo-credentials").text,
        client.get("/api/settings/providers").text,
        client.post("/api/github/preview", json={"repo_url": PRIVATE_URL}).text,
        scan_events(client, PRIVATE_URL, force_rerun=True)[0],     # force_rerun: never answered from the scan cache
    ]
    conn = sqlite3.connect(db._DB_PATH)
    telemetry = json.dumps([list(r) for r in conn.execute("SELECT * FROM telemetry").fetchall()], default=str)
    stored = json.dumps([list(r) for r in conn.execute("SELECT findings_json FROM scan_snapshots").fetchall()], default=str)
    conn.close()

    assert any(auth == f"Bearer {TOKEN}" for _, auth, _ in fake.calls)       # it was used for fetching
    assert prompts, "the pipeline should have called the model"
    for channel, text in {"prompts": " ".join(prompts), "logs": caplog.text, "telemetry": telemetry,
                          "responses": " ".join(responses), "stored scans": stored}.items():
        assert TOKEN not in text and "CANARY" not in text, f"credential leaked into {channel}"


# ── the token only ever goes to api.github.com ────────────────────────────────

def test_token_is_not_forwarded_to_another_host_on_redirect():
    handler = fetcher._KeepTokenOnTheSameHost()
    req = urllib.request.Request("https://api.github.com/repos/a/b/contents/x", headers={"Authorization": "Bearer t"})
    elsewhere = handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/steal")
    downgraded = handler.redirect_request(req, None, 302, "Found", {}, "http://api.github.com/repos/a/b/contents/x")
    same_host = handler.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/repos/a/b2/contents/x")
    assert not elsewhere.has_header("Authorization") and not downgraded.has_header("Authorization")
    assert same_host.has_header("Authorization")
    assert fetcher._OPENER is not None and urllib.request._opener is not fetcher._OPENER     # nothing global was installed


def test_token_is_never_sent_to_raw_githubusercontent(env, monkeypatch):
    repo_credentials.set_token("o", TOKEN)                  # a token exists for the public repo's owner too
    seen = []

    def fake(req, timeout=None):
        seen.append((req.full_url, req.get_header("Authorization")))
        return FakeResponse(b"x = 1\n")

    monkeypatch.setattr(fetcher, "_urlopen", fake)
    fetcher._open("https://raw.githubusercontent.com/o/public/main/a.py", "o", "public", "*/*")
    assert seen == [("https://raw.githubusercontent.com/o/public/main/a.py", None)]


# ── review follow-ups ─────────────────────────────────────────────────────────

def test_a_token_with_a_line_break_or_odd_characters_is_refused_on_save(env, client, monkeypatch):
    install(monkeypatch)
    for bad in ("github_pat_abc\ndef_0123456789", "github pat with spaces 1234", "github_pat_\u00e9\u00e9_0123456789", "short"):
        r = client.put("/api/settings/repo-credentials", json={"owner": "acme", "token": bad})
        assert r.status_code == 422 and "printable" in r.json()["detail"], bad
    assert client.get("/api/settings/repo-credentials").json() == []


def test_the_catch_all_must_be_explicit(env, client, monkeypatch):
    install(monkeypatch)
    assert client.put("/api/settings/repo-credentials", json={"owner": "", "token": TOKEN}).status_code == 422
    assert client.put("/api/settings/repo-credentials", json={"owner": "*", "token": TOKEN}).status_code == 200


def test_a_malformed_stored_token_never_reaches_an_error_message(env, client, monkeypatch):
    bad = "github_pat_LEAK\nCANARY_0123456789"
    repo_credentials.set_token("acme", bad)                 # stored by an older version, or edited by hand

    def refuse(req, timeout=None):
        raise ValueError(f"Invalid header value {req.get_header('Authorization').encode()!r}")

    monkeypatch.setattr(fetcher, "_urlopen", refuse)
    body, events = scan_events(client, PRIVATE_URL)
    assert "CANARY" not in body and "LEAK" not in body
    err = next(e for e in events if e["stage"] == "error")
    assert err["code"] == "token_invalid" and "Settings" in err["msg"]


def test_error_paths_and_delete_responses_do_not_leak_the_credential(env, client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    repo_credentials.set_token("acme", TOKEN)
    texts = []
    for kw in ({"revoked": True}, {"rate_limited": True}, {"token_without_access": True}):
        install(monkeypatch, **kw)
        texts.append(scan_events(client, PRIVATE_URL)[0])
        texts.append(client.post("/api/github/preview", json={"repo_url": PRIVATE_URL}).text)
    texts.append(client.delete("/api/settings/repo-credentials", params={"owner": "acme"}).text)
    assert TOKEN not in " ".join(texts) and TOKEN not in caplog.text


def test_scans_that_use_a_stored_token_are_audited(env, real_auth, monkeypatch):
    from api.main import app
    monkeypatch.setenv("FMEA_COOKIE_SECURE", "0")
    install(monkeypatch)
    stub_pipeline(monkeypatch)
    admin = TestClient(app, headers={"X-Requested-With": "fmea"})
    admin.post("/api/auth/setup", json={"username": "root", "password": "correct-horse-battery"})
    admin.put("/api/settings/repo-credentials", json={"owner": "acme", "token": TOKEN})
    admin.post("/api/users", json={"username": "dana", "password": "correct-horse-battery", "role": "developer"})
    dev = TestClient(app, headers={"X-Requested-With": "fmea"})
    dev.post("/api/auth/login", json={"username": "dana", "password": "correct-horse-battery"})
    scan_events(dev, PRIVATE_URL)
    scan_events(dev, PUBLIC_URL)                            # no token for this owner: not recorded
    conn = sqlite3.connect(db._DB_PATH)
    rows = conn.execute("SELECT username, detail FROM audit_events WHERE action='scan_with_stored_token'").fetchall()
    conn.close()
    assert rows == [("dana", "acme/private-repo")]


def test_repository_urls_with_odd_owner_repo_or_branch_are_refused():
    for url in ("https://github.com/a@b/repo", "https://github.com/../repo", "https://github.com/o/r/tree/x%2fy",
                "https://github.com/o/r/tree/a&b", "https://github.com/o/re?po"):
        with pytest.raises(ValueError):
            fetcher.parse_github_url(url)
    assert fetcher.parse_github_url("https://github.com/o/r.js/tree/feature-1.2").branch == "feature-1.2"


def test_repository_tokens_are_encrypted_when_a_secret_key_appears_later_and_flagged_when_unreadable(env, monkeypatch):
    from cryptography.fernet import Fernet
    from core import secrets as vault
    monkeypatch.delenv("FMEA_SECRET_KEY")
    repo_credentials.set_token("acme", TOKEN)                         # saved as plain text
    assert TOKEN in (env / "settings.json").read_text(encoding="utf-8")
    monkeypatch.setenv("FMEA_SECRET_KEY", SECRET)
    vault.encrypt_stored_keys()
    assert TOKEN not in (env / "settings.json").read_text(encoding="utf-8")
    assert repo_credentials.token_for("acme") == TOKEN
    monkeypatch.setenv("FMEA_SECRET_KEY", Fernet.generate_key().decode())
    assert vault.undecryptable_providers() == ["github:acme"]
