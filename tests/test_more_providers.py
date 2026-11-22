"""
B-047 — more model providers (ADR-030): Anthropic, Azure OpenAI and a local OpenAI-compatible endpoint.

  AC  each new provider passes the provider tests with a fake client (request shape, key, token parameter)
  AC  a local OpenAI-compatible endpoint is configurable (base URL, optional key, own model names)
  AC  adding a provider still needs only registry entries (existing test_providers AC5)
  (live runs on a hosted provider and a local scan are recorded separately: see the backlog entry)
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import core.llm as llm
import core.providers as providers
import core.settings as settings
from core.costs import AVAILABLE_MODELS, all_models, compute_cost, get_rates

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    for p in providers.PROVIDERS.values():
        monkeypatch.delenv(p["env_var"], raising=False)
        monkeypatch.delenv(p.get("endpoint_env", "UNSET_ENDPOINT_VAR"), raising=False)
    llm._clients.clear()
    monkeypatch.setattr(providers, "verify_key", lambda provider_id, key: "valid")


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


class FakeOpenAI:
    """Stands in for openai.OpenAI: records how the client is built and what each request carries."""
    built: list[dict] = []
    requests: list[dict] = []

    def __init__(self, api_key=None, base_url=None, **kw):
        FakeOpenAI.built.append({"api_key": api_key, "base_url": base_url})
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        FakeOpenAI.requests.append(kw)
        message = SimpleNamespace(content='{"ok": true}', tool_calls=None, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


@pytest.fixture
def fake(monkeypatch):
    FakeOpenAI.built, FakeOpenAI.requests = [], []
    monkeypatch.setattr(llm.openai, "OpenAI", FakeOpenAI)
    return FakeOpenAI


# ── registry ──────────────────────────────────────────────────────────────────

def test_the_registry_has_the_three_new_providers_and_every_model_maps_to_one():
    assert {"anthropic", "azure", "local"} <= set(providers.PROVIDERS)
    assert all(m["provider"] in providers.PROVIDERS for m in AVAILABLE_MODELS)
    assert {"anthropic"} <= {m["provider"] for m in AVAILABLE_MODELS}


def test_every_registry_model_is_priced_or_says_it_is_not():
    for m in AVAILABLE_MODELS:
        assert m["id"] in __import__("core.costs", fromlist=["x"]).FALLBACK_RATES or m.get("priced") is False


# ── request shape ─────────────────────────────────────────────────────────────

def test_anthropic_requests_use_its_endpoint_max_tokens_and_no_temperature(fake):
    providers.set_api_key("anthropic", "sk-ant-1234")
    model = next(m["id"] for m in AVAILABLE_MODELS if m["provider"] == "anthropic")
    settings.set_setting("active_model", model)
    llm.call_llm("say {json}", max_tokens=500)
    assert fake.built[-1] == {"api_key": "sk-ant-1234", "base_url": "https://api.anthropic.com/v1/"}
    req = fake.requests[-1]
    assert req["model"] == model and "max_tokens" in req and "max_completion_tokens" not in req
    assert "temperature" not in req                                           # newer Claude models reject values below 1


def test_azure_uses_the_users_endpoint_deployment_name_and_the_completion_token_parameter(fake):
    providers.set_api_key("azure", "az-key-9999")
    providers.set_endpoint("azure", "https://acme.openai.azure.com/openai/v1/")
    providers.add_custom_model("azure", "gpt-4o-prod", "GPT-4o (prod deployment)")
    settings.set_setting("active_model", "gpt-4o-prod")
    llm.call_llm("hello", max_tokens=300)
    assert fake.built[-1] == {"api_key": "az-key-9999", "base_url": "https://acme.openai.azure.com/openai/v1/"}
    req = fake.requests[-1]
    assert req["model"] == "gpt-4o-prod" and "max_completion_tokens" in req and "max_tokens" not in req
    assert req["temperature"] == 0.2


def test_a_local_endpoint_needs_no_key_and_uses_the_users_model_name(fake):
    providers.set_endpoint("local", "http://localhost:11434/v1")
    providers.add_custom_model("local", "llama3.1:70b", "Llama 3.1 70B")
    settings.set_setting("active_model", "llama3.1:70b")
    llm.call_llm("hello", max_tokens=300)
    assert fake.built[-1]["base_url"] == "http://localhost:11434/v1" and fake.built[-1]["api_key"]    # the SDK needs some value
    assert fake.requests[-1]["model"] == "llama3.1:70b" and "max_tokens" in fake.requests[-1]


def test_a_changed_endpoint_builds_a_new_client(fake):
    providers.set_endpoint("local", "http://a:1/v1")
    providers.add_custom_model("local", "m", "M")
    settings.set_setting("active_model", "m")
    llm.call_llm("x")
    providers.set_endpoint("local", "http://b:2/v1")
    llm.call_llm("x")
    assert [b["base_url"] for b in fake.built] == ["http://a:1/v1", "http://b:2/v1"]


def test_an_unconfigured_provider_says_what_is_missing(fake):
    providers.add_custom_model("azure", "dep", "Dep")
    providers.set_api_key("azure", "k")
    settings.set_setting("active_model", "dep")
    with pytest.raises(llm.MissingApiKeyError, match="endpoint"):
        llm.call_llm("x")
    assert not providers.is_configured("azure")


# ── configuration ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("provider,url,ok", [
    ("azure", "https://acme.openai.azure.com/openai/v1/", True),
    ("azure", "http://acme.openai.azure.com/openai/v1/", False),     # keys must not travel in the clear
    ("local", "http://localhost:11434/v1", True),
    ("local", "https://llm.internal.example/v1", True),
    ("local", "ftp://x/v1", False),
    ("local", "http://user:pass@host/v1", False),
    ("local", "not a url", False),
    ("anthropic", "https://elsewhere.example/v1", False),            # fixed endpoint
])
def test_endpoints_are_validated(client, provider, url, ok):
    r = client.put(f"/api/settings/providers/{provider}/endpoint", json={"endpoint": url})
    assert (r.status_code == 200) is ok


def test_the_endpoint_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://gpu-box:8000/v1")
    assert providers.get_endpoint("local") == "http://gpu-box:8000/v1"


def test_providers_list_shows_endpoint_and_whether_each_is_ready(client):
    client.put("/api/settings/providers/local/endpoint", json={"endpoint": "http://localhost:11434/v1"})
    rows = {p["id"]: p for p in client.get("/api/settings/providers").json()}
    assert rows["local"]["configured"] is True and rows["local"]["key_optional"] is True
    assert rows["local"]["endpoint"] == "http://localhost:11434/v1" and rows["local"]["endpoint_editable"] is True
    assert rows["azure"]["configured"] is False and rows["anthropic"]["endpoint_editable"] is False


def test_custom_models_are_added_listed_activated_and_removed(client):
    client.put("/api/settings/providers/local/endpoint", json={"endpoint": "http://localhost:11434/v1"})
    r = client.post("/api/settings/models/custom", json={"provider": "local", "id": "qwen2.5-coder", "display": "Qwen coder"})
    assert r.status_code == 200
    listed = {m["id"]: m for m in client.get("/api/settings/models").json()}
    assert listed["qwen2.5-coder"]["provider"] == "local" and listed["qwen2.5-coder"]["key_set"] is True
    assert client.patch("/api/settings/model", json={"model": "qwen2.5-coder"}).status_code == 200
    assert providers.provider_for_model("qwen2.5-coder") == "local"
    assert client.delete("/api/settings/models/custom/qwen2.5-coder").status_code == 200
    assert "qwen2.5-coder" not in {m["id"] for m in client.get("/api/settings/models").json()}


@pytest.mark.parametrize("body", [
    {"provider": "anthropic", "id": "x", "display": "X"},            # fixed list
    {"provider": "nope", "id": "x", "display": "X"},
    {"provider": "local", "id": "  ", "display": "X"},
    {"provider": "local", "id": "gpt-4o", "display": "clashes with a built-in model"},
])
def test_bad_custom_models_are_rejected(client, body):
    assert client.post("/api/settings/models/custom", json=body).status_code in (404, 409, 422)


def test_a_model_cannot_be_activated_until_its_provider_is_configured(client):
    providers.add_custom_model("azure", "dep", "Dep")
    assert client.patch("/api/settings/model", json={"model": "dep"}).status_code == 409
    client.put("/api/settings/providers/azure/endpoint", json={"endpoint": "https://a.openai.azure.com/openai/v1/"})
    assert client.patch("/api/settings/model", json={"model": "dep"}).status_code == 409           # still no key
    client.put("/api/settings/providers/azure/key", json={"api_key": "k-1234"})
    assert client.patch("/api/settings/model", json={"model": "dep"}).status_code == 200


def test_new_routes_are_in_the_role_policy_and_need_the_settings_role():
    from api.policy import POLICY
    for route in (("PUT", "/api/settings/providers/{provider_id}/endpoint"), ("POST", "/api/settings/models/custom"),
                  ("DELETE", "/api/settings/models/custom/{model_id:path}")):
        assert POLICY[route] == "settings"


# ── cost ──────────────────────────────────────────────────────────────────────

def test_a_local_model_costs_nothing_and_an_unpriced_hosted_one_is_estimated_conservatively():
    providers.add_custom_model("local", "llama", "Llama")
    providers.add_custom_model("azure", "dep", "Dep")
    assert compute_cost("llama", 1_000_000, 1_000_000) == 0.0
    assert get_rates("dep") == get_rates("gpt-5.1")                      # a spend limit must still bite
    providers.add_custom_model("azure", "priced", "Priced", prompt_per_1m=1.0, completion_per_1m=2.0)
    assert compute_cost("priced", 1_000_000, 1_000_000) == 3.0


def test_the_models_list_flags_unknown_prices(client):
    providers.add_custom_model("azure", "dep", "Dep")
    row = next(m for m in client.get("/api/settings/models").json() if m["id"] == "dep")
    assert row["rates_known"] is False
    gpt = next(m for m in client.get("/api/settings/models").json() if m["id"] == "gpt-5.1")
    assert gpt["rates_known"] is True


def test_pricing_refresh_survives_models_without_a_fallback_price(client, monkeypatch):
    import api.routers.settings as router
    monkeypatch.setattr(router, "refresh_pricing", lambda: {})
    assert client.post("/api/settings/pricing/refresh").status_code == 200


def test_the_estimate_marks_a_custom_model_price_as_assumed(monkeypatch):
    import core.estimate as estimator
    providers.add_custom_model("azure", "dep", "Dep")
    monkeypatch.setattr(estimator, "get_model_name", lambda: "dep")
    assert estimator.estimate_scan([100_000])["rates_known"] is False


# ── embeddings: none of the new providers has one ────────────────────────────

def test_without_an_embedding_model_scenario_matching_falls_back_to_names_and_identity(monkeypatch):
    import memory.scenario_registry as registry
    settings.set_setting("active_model", next(m["id"] for m in AVAILABLE_MODELS if m["provider"] == "anthropic"))
    assert registry.current_embed_model() is None
    locked = [{"failure_mode": "A", "embedding": b"\x00" * 8, "embed_model": "text-embedding-3-small"}]
    monkeypatch.setattr(registry, "embed_text", lambda text: (_ for _ in ()).throw(AssertionError("must not embed")))
    assert registry.find_matching_scenario("B", ["step"], locked) is None


# ── interface and docs ────────────────────────────────────────────────────────

def test_the_settings_panel_lets_the_user_set_an_endpoint_and_add_a_model():
    header = (ROOT / "frontend/src/components/Header.jsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api.js").read_text(encoding="utf-8")
    assert "endpoint_editable" in header and "addCustomModel" in header
    assert "/endpoint" in api and "/api/settings/models/custom" in api


def test_the_decision_is_recorded():
    adr = (ROOT / "docs/decisions/ADR-030-more-model-providers.md").read_text(encoding="utf-8")
    assert "Bedrock" in adr and "Anthropic" in adr and "Status:" in adr


REAL_VERIFY_KEY = providers.verify_key                                  # captured before the fixture replaces it

# ── review follow-ups ─────────────────────────────────────────────────────────

def test_pricing_refresh_with_a_live_payload_skips_models_without_a_price(monkeypatch):
    import io
    import core.costs as costs
    payload = json.dumps({"gpt-5.1": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}}).encode()
    monkeypatch.setattr(costs.urllib.request, "urlopen", lambda url, timeout=5: io.BytesIO(payload))
    rates = costs.refresh_pricing()
    assert rates["gpt-5.1"] == {"prompt": 1.0, "completion": 2.0} and "claude-opus-5-5" not in rates
    assert settings.get_setting("pricing_cache") == rates


def test_a_key_is_never_checked_or_stored_before_the_endpoint_exists(client):
    assert client.put("/api/settings/providers/azure/key", json={"api_key": "secret-1"}).status_code == 409
    assert providers.get_api_key("azure") is None


def test_verify_key_does_not_reach_the_default_host_without_an_endpoint(monkeypatch):
    constructed = []
    monkeypatch.setattr(providers.openai, "OpenAI", lambda **kw: constructed.append(kw))
    assert REAL_VERIFY_KEY("azure", "k") == "unverified" and constructed == []


@pytest.mark.parametrize("provider,url", [
    ("azure", "https://169.254.169.254/openai/v1/"), ("local", "http://169.254.169.254/"), ("local", "http://metadata.google.internal/"),
    ("azure", "https://10.0.0.5/openai/v1/"), ("azure", "https://127.0.0.1/v1"), ("local", "http://host:99999/v1"), ("local", "http://[fe80::1]/v1"),
])
def test_dangerous_or_broken_endpoints_are_refused(provider, url):
    with pytest.raises(ValueError):
        providers.validate_endpoint(provider, url)


def test_a_private_address_is_fine_for_a_local_endpoint():
    assert providers.validate_endpoint("local", "http://10.0.0.5:8000/v1") == "http://10.0.0.5:8000/v1"


def test_an_environment_endpoint_gets_the_same_checks(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "http://insecure.example/openai/v1/")
    assert providers.get_endpoint("azure") is None
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://acme.openai.azure.com/openai/v1/")
    assert providers.get_endpoint("azure") == "https://acme.openai.azure.com/openai/v1/"


def test_changing_the_endpoint_clears_the_stored_key():
    providers.set_endpoint("azure", "https://a.openai.azure.com/openai/v1/")
    providers.set_api_key("azure", "k-1")
    providers.set_endpoint("azure", "https://a.openai.azure.com/openai/v1/")
    assert providers.get_api_key("azure") == "k-1"                          # same host: kept
    providers.set_endpoint("azure", "https://b.openai.azure.com/openai/v1/")
    assert providers.get_api_key("azure") is None


@pytest.mark.parametrize("prices", [(-1.0, 1.0), (float("nan"), 1.0), (1.0, float("inf")), (1.0, None)])
def test_bad_custom_prices_are_refused(prices):
    with pytest.raises(ValueError):
        providers.add_custom_model("azure", "dep", "Dep", *prices)


def test_custom_model_ids_with_slashes_can_be_removed_and_unknown_ones_are_404(client):
    client.put("/api/settings/providers/local/endpoint", json={"endpoint": "http://localhost:8000/v1"})
    client.post("/api/settings/models/custom", json={"provider": "local", "id": "meta-llama/Llama-3.1-8B", "display": "Llama"})
    assert client.delete("/api/settings/models/custom/meta-llama/Llama-3.1-8B").status_code == 200
    assert client.delete("/api/settings/models/custom/meta-llama/Llama-3.1-8B").status_code == 404
    assert client.delete("/api/settings/models/custom/claude-opus-5-5").status_code == 404
    assert settings.get_setting("active_model") == "gpt-5.1"


def test_chat_accepts_a_keyless_local_model():
    import core.chat as chat
    providers.set_endpoint("local", "http://localhost:11434/v1")
    providers.add_custom_model("local", "llama", "Llama")
    settings.set_setting("active_model", "llama")
    assert chat.is_configured(providers.provider_for_model("llama"))


def test_reasoning_lookup_knows_custom_models():
    import core.reasoning as reasoning
    providers.add_custom_model("local", "llama", "Llama")
    assert reasoning.supported_levels("llama") is not None
