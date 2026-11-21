"""
B-048 phase 0 — UX blockers: plain scan errors (U13), key validation and status (U14),
placeholders removed (U8).

  AC: an expired key gives a plain message and a Settings action, never raw provider text
  AC: saving an invalid key is rejected; Settings shows key status per provider
  AC: no "Acme", "demo@fmea.io" or "coming soon" in frontend/src
"""

import json
import re
from pathlib import Path

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

import core.llm as llm
import core.providers as providers
import core.settings as settings

ROOT = Path(__file__).resolve().parent.parent
RAW_401 = "Error code: 401 - {'detail': 'Your API key expired on 2026-11-17'}"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    for p in providers.PROVIDERS.values():
        monkeypatch.delenv(p["env_var"], raising=False)
    llm._clients.clear()
    settings.set_setting("active_model", "mistral-medium-latest")


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _auth_error() -> openai.AuthenticationError:
    req = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
    return openai.AuthenticationError(RAW_401, response=httpx.Response(401, request=req), body=None)


def _sse_events(text: str) -> list[tuple[str, dict]]:
    out = []
    for frame in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in frame.splitlines() if ": " in l)
        out.append((lines.get("event", "message"), json.loads(lines["data"])))
    return out


# ── U13: plain scan errors ────────────────────────────────────────────────────

def test_expired_key_scan_error_is_plain_and_offers_settings(client, monkeypatch):
    def boom(*a, **k):
        raise _auth_error()
    monkeypatch.setattr("api.routers.scan.run_fmea", boom)

    r = client.post("/api/scan", json={"code": "print(1)"})
    errors = [d for ev, d in _sse_events(r.text) if ev == "error"]

    assert len(errors) == 1
    err = errors[0]
    assert err["code"] == "key_invalid"
    assert err["action"] == "open_settings"
    assert "Mistral" in err["msg"]
    assert "401" not in err["msg"] and "Error code" not in err["msg"] and "detail" not in err["msg"]


def test_expired_key_marks_provider_status_invalid(client, monkeypatch):
    providers.set_api_key("mistral", "k-1234")

    def boom(*a, **k):
        raise _auth_error()
    monkeypatch.setattr("api.routers.scan.run_fmea", boom)
    client.post("/api/scan", json={"code": "print(1)"})

    status = {p["id"]: p["status"] for p in client.get("/api/settings/providers").json()}
    assert status["mistral"] == "invalid"


def test_missing_key_unknown_and_rate_limit_errors_are_plain():
    from core.llm_errors import scan_error_event

    missing = scan_error_event(llm.MissingApiKeyError("No API key for Mistral AI. Enter one ..."))
    assert missing["code"] == "key_missing" and missing["action"] == "open_settings"

    req = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
    limited = scan_error_event(
        openai.RateLimitError("429 raw", response=httpx.Response(429, request=req), body=None))
    assert limited["code"] == "rate_limited" and "429" not in limited["msg"]

    other = scan_error_event(ValueError("/home/user/secret/path exploded"))
    assert other["code"] == "scan_failed" and "secret" not in other["msg"]
    assert other.get("action") is None


# ── U14: key validation and status ────────────────────────────────────────────

class _FakeModels:
    def __init__(self, exc): self._exc = exc
    def list(self):
        if self._exc:
            raise self._exc
        return []


def _fake_openai(monkeypatch, exc=None):
    class _Client:
        def __init__(self, **kw): self.models = _FakeModels(exc)
    monkeypatch.setattr(providers.openai, "OpenAI", _Client)


def test_verify_key_classifies_valid_invalid_and_unreachable(monkeypatch):
    _fake_openai(monkeypatch)
    assert providers.verify_key("mistral", "k") == "valid"
    _fake_openai(monkeypatch, _auth_error())
    assert providers.verify_key("mistral", "k") == "invalid"
    _fake_openai(monkeypatch, openai.APIConnectionError(request=httpx.Request("GET", "https://x")))
    assert providers.verify_key("mistral", "k") == "unverified"


def test_saving_invalid_key_is_rejected_and_not_stored(client, monkeypatch):
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "invalid")
    r = client.put("/api/settings/providers/mistral/key", json={"api_key": "bad-key-0000"})
    assert r.status_code == 422
    assert "Mistral" in r.json()["detail"] and "bad-key" not in r.json()["detail"]
    assert providers.get_api_key("mistral") is None


def test_saving_valid_key_records_status(client, monkeypatch):
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "valid")
    r = client.put("/api/settings/providers/openai/key", json={"api_key": "good-key-1111"})
    assert r.status_code == 200 and r.json()["status"] == "valid"


def test_unreachable_provider_saves_key_as_unverified(client, monkeypatch):
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "unverified")
    r = client.put("/api/settings/providers/openai/key", json={"api_key": "maybe-key-2222"})
    assert r.status_code == 200 and r.json()["status"] == "unverified"
    assert providers.get_api_key("openai") == "maybe-key-2222"


def test_providers_list_shows_status_per_provider(client, monkeypatch):
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "valid")
    client.put("/api/settings/providers/openai/key", json={"api_key": "good-key-1111"})
    monkeypatch.setenv("MISTRAL_API_KEY", "env-key-3333")

    status = {p["id"]: p["status"] for p in client.get("/api/settings/providers").json()}
    assert status == {"openai": "valid", "mistral": "unchecked"}   # env key not yet checked
    client.delete("/api/settings/providers/openai/key")
    monkeypatch.delenv("MISTRAL_API_KEY")
    status = {p["id"]: p["status"] for p in client.get("/api/settings/providers").json()}
    assert status == {"openai": "missing", "mistral": "missing"}


def test_verify_endpoint_rechecks_and_updates_status(client, monkeypatch):
    providers.set_api_key("mistral", "k-1234")
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "invalid")
    r = client.post("/api/settings/providers/mistral/verify")
    assert r.status_code == 200 and r.json()["status"] == "invalid"
    assert client.post("/api/settings/providers/openai/verify").json()["status"] == "missing"
    assert client.post("/api/settings/providers/nope/verify").status_code == 404


def test_status_response_never_contains_the_key(client, monkeypatch):
    monkeypatch.setattr(providers, "verify_key", lambda pid, key: "valid")
    client.put("/api/settings/providers/openai/key", json={"api_key": "sk-very-secret-9999"})
    assert "very-secret" not in client.get("/api/settings/providers").text
    assert "very-secret" not in client.post("/api/settings/providers/openai/verify").text


# ── U8: placeholders removed ──────────────────────────────────────────────────

def test_no_placeholders_in_frontend_source():
    pattern = re.compile(r"Acme|demo@fmea\.io|coming soon|Within 7 days", re.IGNORECASE)
    hits = [
        f"{f.relative_to(ROOT)}:{n}"
        for f in sorted((ROOT / "frontend" / "src").rglob("*"))
        if f.suffix in {".js", ".jsx", ".css", ".html"}
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert hits == []
