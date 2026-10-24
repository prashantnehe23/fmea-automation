"""
tests/test_llm_adaptive.py — B-024: adaptive handling of verbose / truncated model output

  AC1: First attempt budget is wide (a ceiling, not the agent's small expected size)
  AC2: JSON cut off by the limit is continued, not discarded (models that restart are not glued)
  AC3: Analysis without JSON triggers a recovery pass that keeps the analysis in context
  AC4: Truncated JSON is salvaged, keeping every completed item
  AC5: Plain-text prompts never trigger JSON recovery
  AC6: Unrecoverable truncation raises a clear error
"""

import json
from types import SimpleNamespace as NS

import pytest

import core.llm as llm
import core.providers as providers
import core.settings as settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    for p in providers.PROVIDERS.values():
        monkeypatch.delenv(p["env_var"], raising=False)
    llm._clients.clear()
    providers.set_api_key("mistral", "k")
    providers.set_api_key("openai", "k")


def fake(monkeypatch, replies):
    calls = []

    class Fake:
        def __init__(self, api_key, base_url=None):
            self.chat = self
            self.completions = self

        def create(self, **kw):
            calls.append(kw)
            content, finish = replies[min(len(calls), len(replies)) - 1]
            return NS(usage=NS(prompt_tokens=10, completion_tokens=5),
                      choices=[NS(finish_reason=finish, message=NS(content=content))])

    monkeypatch.setattr(llm.openai, "OpenAI", Fake)
    return calls


JSON_PROMPT = "Analyse this. Return JSON only."


def test_first_budget_is_wide_not_agent_sized(monkeypatch):
    calls = fake(monkeypatch, [('{"a": 1}', "stop")])
    settings.set_setting("active_model", "mistral-large-4")
    llm.call_llm(JSON_PROMPT, max_tokens=2000)
    assert calls[0]["max_tokens"] == llm.FIRST_ATTEMPT_FLOOR


def test_truncated_json_is_continued_not_discarded(monkeypatch):
    calls = fake(monkeypatch, [('{"items": [1, 2,', "length"), (" 3]}", "stop")])
    for model in ("mistral-large-4", "gpt-4o-mini"):
        calls.clear()
        settings.set_setting("active_model", model)
        assert json.loads(llm.call_llm(JSON_PROMPT)) == {"items": [1, 2, 3]}
        msgs = calls[1]["messages"]
        assert msgs[1] == {"role": "assistant", "content": '{"items": [1, 2,'}
        assert msgs[2]["role"] == "user" and "cut off" in msgs[2]["content"]


def test_model_that_restarts_instead_of_resuming_is_not_glued(monkeypatch):
    fake(monkeypatch, [('{"items": [1, 2,', "length"), ('```json\n{"items": [1, 2, 3]}\n```', "stop")])
    settings.set_setting("active_model", "mistral-large-4")
    assert json.loads(llm.extract_json_text(llm.call_llm(JSON_PROMPT))) == {"items": [1, 2, 3]}


def test_analysis_without_json_is_recovered_with_analysis_in_context(monkeypatch):
    essay = "## Perspective 1\nLots of analysis...\n## Synthesis\nDone."
    calls = fake(monkeypatch, [(essay, "stop"), ('```json\n{"tiering": {"x": "Tier 1"}}\n```', "stop")])
    settings.set_setting("active_model", "mistral-large-4")
    out = llm.call_llm(JSON_PROMPT)
    assert json.loads(llm.extract_json_text(out)) == {"tiering": {"x": "Tier 1"}}
    msgs = calls[1]["messages"]
    assert msgs[1] == {"role": "assistant", "content": essay}
    assert "ONLY the final JSON" in msgs[2]["content"]


def test_truncated_essay_is_also_recovered(monkeypatch):
    fake(monkeypatch, [("long analysis cut off mid", "length"), ('{"ok": true}', "stop")])
    settings.set_setting("active_model", "mistral-large-4")
    assert json.loads(llm.call_llm(JSON_PROMPT)) == {"ok": True}


def test_exhausted_continuations_salvage_completed_items(monkeypatch):
    chunk = '[{"id": 1}, {"id": 2}, {"id'
    fake(monkeypatch, [(chunk, "length")])
    settings.set_setting("active_model", "mistral-large-4")
    assert json.loads(llm.call_llm(JSON_PROMPT)) == [{"id": 1}, {"id": 2}]


def test_plain_text_prompt_never_runs_json_recovery(monkeypatch):
    calls = fake(monkeypatch, [("Two sentences of prose.", "stop")])
    settings.set_setting("active_model", "mistral-large-4")
    assert llm.call_llm("Write 2-3 sentences, plain prose.") == "Two sentences of prose."
    assert len(calls) == 1


def test_unrecoverable_truncation_raises_clear_error(monkeypatch):
    fake(monkeypatch, [("no json here at all", "length")])
    settings.set_setting("active_model", "gpt-4o-mini")
    with pytest.raises(RuntimeError, match="output limit"):
        llm.call_llm(JSON_PROMPT)


@pytest.mark.parametrize("text, expected", [
    ('{"a": [1, 2], "b": "te', {"a": [1, 2]}),
    ('{"a": 1, "b"', {"a": 1}),
    ('```json\n[{"x": 1}, {"x": 2},', [{"x": 1}, {"x": 2}]),
])
def test_salvage_json(text, expected):
    assert json.loads(llm._salvage_json(text)) == expected


def test_salvage_returns_none_when_nothing_usable():
    assert llm._salvage_json("plain words only") is None


def test_complete_but_malformed_json_is_not_cut_down(monkeypatch):
    bad = '[{"id": 1} {"id": 2} {"id": 3}] oops "'
    fake(monkeypatch, [(bad, "stop"), (bad, "stop")])
    settings.set_setting("active_model", "mistral-large-4")
    out = llm.call_llm(JSON_PROMPT)
    assert "id\": 3" in out  # nothing dropped: returned for the agent to handle
