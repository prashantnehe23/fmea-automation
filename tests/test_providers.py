"""
tests/test_providers.py — B-022: Multi-provider model + API key selection

  AC1: Registry lists OpenAI and Mistral models, each mapped to a known provider
  AC2: Keys are stored, masked, never returned raw; env var is a fallback
  AC3: Model cannot be activated without a key for its provider
  AC4: call_llm routes to the model's provider (base_url, key, token param)
  AC5: A new provider needs only registry entries (no code changes)
"""

import pytest
from fastapi.testclient import TestClient

import core.settings as settings
import core.llm as llm
import core.providers as providers
from core.costs import AVAILABLE_MODELS, FALLBACK_RATES


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    for p in providers.PROVIDERS.values():
        monkeypatch.delenv(p["env_var"], raising=False)
    llm._clients.clear()


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def test_registry_models_map_to_providers_and_have_rates():
    ids = {m["provider"] for m in AVAILABLE_MODELS}
    assert {"openai", "mistral"} <= ids
    for m in AVAILABLE_MODELS:
        assert m["provider"] in providers.PROVIDERS
        assert m["id"] in FALLBACK_RATES


def test_key_stored_masked_and_not_leaked(client):
    r = client.put("/api/settings/providers/mistral/key", json={"api_key": "sk-secret-1234"})
    assert r.status_code == 200 and r.json()["key_hint"] == "••••1234"
    body = client.get("/api/settings/providers").text
    assert "sk-secret" not in body
    assert providers.get_api_key("mistral") == "sk-secret-1234"
    assert client.delete("/api/settings/providers/mistral/key").json()["key_set"] is False


def test_env_var_fallback(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "env-key-9999")
    assert providers.get_api_key("mistral") == "env-key-9999"


def test_unknown_provider_and_empty_key_rejected(client):
    assert client.put("/api/settings/providers/nope/key", json={"api_key": "x"}).status_code == 404
    assert client.put("/api/settings/providers/openai/key", json={"api_key": "  "}).status_code == 422


def test_model_requires_provider_key(client):
    assert client.patch("/api/settings/model", json={"model": "mistral-large-latest"}).status_code == 409
    client.put("/api/settings/providers/mistral/key", json={"api_key": "k-1234"})
    assert client.patch("/api/settings/model", json={"model": "mistral-large-latest"}).status_code == 200
    assert settings.get_setting("active_model") == "mistral-large-latest"


def test_call_llm_routes_to_provider(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, api_key, base_url=None):
            captured["api_key"], captured["base_url"] = api_key, base_url
            self.chat = self
            self.completions = self

        def create(self, **kw):
            captured["kw"] = kw
            from types import SimpleNamespace as NS
            return NS(usage=NS(prompt_tokens=1, completion_tokens=1),
                      choices=[NS(message=NS(content="ok"))])

    monkeypatch.setattr(llm.openai, "OpenAI", FakeOpenAI)
    providers.set_api_key("mistral", "m-key")
    settings.set_setting("active_model", "mistral-small-latest")
    assert llm.call_llm("hi", max_tokens=50) == "ok"
    assert captured["base_url"] == "https://api.mistral.ai/v1"
    assert captured["api_key"] == "m-key"
    assert captured["kw"]["max_tokens"] == 50 and "max_completion_tokens" not in captured["kw"]

    providers.set_api_key("openai", "o-key")
    settings.set_setting("active_model", "gpt-4o-mini")
    llm.call_llm("hi", max_tokens=50)
    assert captured["api_key"] == "o-key"
    assert captured["kw"]["max_completion_tokens"] == 50


def test_missing_key_gives_clear_error():
    settings.set_setting("active_model", "mistral-small-latest")
    with pytest.raises(RuntimeError, match="Mistral AI"):
        llm.call_llm("hi")


def test_new_provider_is_registry_only(monkeypatch):
    monkeypatch.setitem(providers.PROVIDERS, "acme", {
        "display": "Acme", "base_url": "https://acme.example/v1",
        "env_var": "ACME_API_KEY", "max_tokens_param": "max_tokens"})
    monkeypatch.setattr("core.costs.AVAILABLE_MODELS",
                        AVAILABLE_MODELS + [{"id": "acme-1", "provider": "acme", "display": "Acme 1", "tier": "Fast"}])
    providers.set_api_key("acme", "a-key")
    assert providers.provider_for_model("acme-1") == "acme"
    assert providers.get_api_key("acme") == "a-key"
