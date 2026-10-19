"""
tests/test_reasoning.py — B-023: user-selectable reasoning level

  AC1: Registry declares which levels each model supports; unsupported levels never sent
  AC2: Level resolves to the nearest supported level at or below the chosen one
  AC3: Reasoning param and scaled max_tokens reach the provider request
  AC4: Token budget is capped per model and truncation retry still works
  AC5: Settings API reads/writes the level; models list exposes levels per model
  AC6: Models without reasoning get no param and no scaling
  AC7: Evaluator cost estimate uses the active model's rates
"""

import pytest
from fastapi.testclient import TestClient

import core.settings as settings
import core.llm as llm
import core.providers as providers
import core.reasoning as reasoning
from core.costs import AVAILABLE_MODELS, compute_cost


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    for p in providers.PROVIDERS.values():
        monkeypatch.delenv(p["env_var"], raising=False)
    llm._clients.clear()


def _fake(monkeypatch, replies=(("ok", "stop"),)):
    from types import SimpleNamespace as NS
    calls = []

    class Fake:
        def __init__(self, api_key, base_url=None):
            self.chat = self
            self.completions = self

        def create(self, **kw):
            calls.append(kw)
            content, finish = replies[min(len(calls), len(replies)) - 1]
            return NS(usage=NS(prompt_tokens=1, completion_tokens=1),
                      choices=[NS(finish_reason=finish, message=NS(content=content))])

    monkeypatch.setattr(llm.openai, "OpenAI", Fake)
    providers.set_api_key("mistral", "k")
    providers.set_api_key("openai", "k")
    return calls


def test_supported_levels_per_model():
    assert reasoning.supported_levels("mistral-large-4") == ["off", "high"]
    assert reasoning.supported_levels("gpt-5.1") == ["off", "low", "medium", "high"]
    assert reasoning.supported_levels("gpt-4o-mini") == []
    assert reasoning.supported_levels("unknown-model") == []


def test_resolve_level_nearest_at_or_below():
    assert reasoning.resolve_level("mistral-large-4", "medium") == "off"
    assert reasoning.resolve_level("mistral-large-4", "high") == "high"
    assert reasoning.resolve_level("gpt-5.1", "low") == "low"
    assert reasoning.resolve_level("gpt-4o", "high") is None


def test_high_sends_param_and_scales_tokens(monkeypatch):
    calls = _fake(monkeypatch)
    settings.set_setting("active_model", "mistral-large-4")
    settings.set_setting("reasoning_level", "high")
    llm.call_llm("hi", max_tokens=6000)
    assert calls[0]["reasoning_effort"] == "high"
    assert calls[0]["max_tokens"] == 24000  # 6000 x 4


def test_off_sends_none_with_base_budget(monkeypatch):
    calls = _fake(monkeypatch)
    settings.set_setting("active_model", "mistral-large-4")
    llm.call_llm("hi", max_tokens=2000)
    assert calls[0]["reasoning_effort"] == "none" and calls[0]["max_tokens"] == llm.FIRST_ATTEMPT_FLOOR


def test_openai_reasoning_uses_its_token_param(monkeypatch):
    calls = _fake(monkeypatch)
    settings.set_setting("active_model", "gpt-5.1")
    settings.set_setting("reasoning_level", "medium")
    llm.call_llm("hi", max_tokens=10000)
    assert calls[0]["reasoning_effort"] == "medium"
    assert calls[0]["max_completion_tokens"] == 25000


def test_non_reasoning_model_unaffected(monkeypatch):
    calls = _fake(monkeypatch)
    settings.set_setting("active_model", "gpt-4o-mini")
    settings.set_setting("reasoning_level", "high")
    llm.call_llm("hi", max_tokens=1000)
    assert "reasoning_effort" not in calls[0] and calls[0]["max_completion_tokens"] == llm.FIRST_ATTEMPT_FLOOR


def test_budget_capped_at_model_max(monkeypatch):
    calls = _fake(monkeypatch)
    settings.set_setting("active_model", "mistral-large-4")
    settings.set_setting("reasoning_level", "high")
    llm.call_llm("hi", max_tokens=20000)  # x4 = 80000 > cap
    assert calls[0]["max_tokens"] == reasoning.DEFAULT_MAX_OUTPUT_TOKENS


def test_continuation_uses_model_ceiling_after_scaled_first_budget(monkeypatch):
    calls = _fake(monkeypatch, [("cut", "length"), ("done", "stop")])
    settings.set_setting("active_model", "mistral-large-4")
    settings.set_setting("reasoning_level", "high")
    assert llm.call_llm("hi", max_tokens=6000) == "cutdone"
    assert [c["max_tokens"] for c in calls] == [24000, reasoning.DEFAULT_MAX_OUTPUT_TOKENS]


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def test_api_reads_and_sets_level(client):
    settings.set_setting("active_model", "mistral-large-4")
    assert client.get("/api/settings/reasoning").json()["level"] == "off"
    r = client.patch("/api/settings/reasoning", json={"level": "high"}).json()
    assert r["level"] == "high" and r["effective"] == "high" and r["token_multiplier"] == 4.0
    assert client.patch("/api/settings/reasoning", json={"level": "extreme"}).status_code == 422


def test_api_effective_level_follows_model_support(client):
    settings.set_setting("active_model", "mistral-large-4")
    r = client.patch("/api/settings/reasoning", json={"level": "medium"}).json()
    assert r["level"] == "medium" and r["effective"] == "off" and r["supported"] == ["off", "high"]
    settings.set_setting("active_model", "gpt-4o")
    assert client.get("/api/settings/reasoning").json()["effective"] is None


def test_models_list_exposes_levels(client):
    models = {m["id"]: m for m in client.get("/api/settings/models").json()}
    assert [x["level"] for x in models["mistral-large-4"]["reasoning_levels"]] == ["off", "high"]
    assert models["gpt-4o-mini"]["reasoning_levels"] == []


def test_every_registry_reasoning_entry_is_valid():
    for m in AVAILABLE_MODELS:
        cfg = m.get("reasoning")
        if cfg:
            assert cfg["param"] and set(cfg["levels"]) <= set(reasoning.LEVELS)


def test_evaluator_cost_uses_active_model_rates():
    from agents.evaluator import _estimate_cost
    settings.set_setting("active_model", "mistral-small-latest")
    small = _estimate_cost(9, 3)
    settings.set_setting("active_model", "gpt-4o")
    assert _estimate_cost(9, 3) > small > 0
