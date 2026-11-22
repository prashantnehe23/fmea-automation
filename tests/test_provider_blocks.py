"""
B-040 — defensive-purpose framing and provider-block handling (ADR-024).

  AC  every prompt builder includes the shared defensive preamble (all agents and the chat)
  AC  no prompt template carries attacker role-play wording or asks for working exploit code
  AC  a Mistral guardrail 403 and an OpenAI content filter / refusal are `provider_blocked`; other errors are not
  AC  a blocked prompt is not retried with the same wording
  AC  the scan and the chat show a plain message and a way to choose another model; the result states its model
  AC  the benchmark report shows the block rate
  (Block rate on Mistral Large 4 and recall after the change need real model runs: see the backlog.)
"""

import json
import re
from types import SimpleNamespace as NS

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

import agents.actuary as actuary
import agents.controls_assessor as controls_assessor
import agents.llm_judge as llm_judge
import agents.saboteur as saboteur
import agents.scenario_linkage as scenario_linkage
import agents.sre_agent as sre_agent
import agents.surveyor as surveyor
import agents.validator as validator
import core.chat as chat
import core.llm as llm
import core.prompt_context as prompt_context
import core.providers as providers
import core.settings as settings
import memory.db as db
from core.models import ControlAssessment, FailureMode, RemediationPlan, RiskScore, SystemContext, ValidationResult
from core.provider_block import ProviderBlocked, is_provider_block

REQUEST = httpx.Request("POST", "https://api.example.com/v1/chat/completions")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    for p in providers.PROVIDERS.values():
        monkeypatch.delenv(p["env_var"], raising=False)
    llm._clients.clear()
    providers.set_api_key("mistral", "k")
    providers.set_api_key("openai", "k")
    settings.set_setting("active_model", "mistral-large-4")


def status_error(cls, status, body, message="provider said no"):
    return cls(message, response=httpx.Response(status, request=REQUEST), body=body)


def mistral_guardrail():
    return status_error(openai.PermissionDeniedError, 403,
                        {"object": "error", "message": "Request blocked by guardrail policy", "type": "guardrail_violation", "code": 1920},
                        "Error code: 403 - Request blocked by guardrail policy")


def openai_filter():
    return status_error(openai.BadRequestError, 400, {"error": {"message": "filtered", "code": "content_filter"}})


class Recorder:
    """A fake OpenAI-compatible client that records every request and answers from a script."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.requests.append(kw)
        reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def install(self, monkeypatch):
        monkeypatch.setattr(llm, "_get_client", lambda provider_id: self)
        return self


def answer(content="[]", finish="stop", refusal=None):
    return NS(usage=NS(prompt_tokens=10, completion_tokens=5),
              choices=[NS(finish_reason=finish, message=NS(content=content, tool_calls=None, refusal=refusal))])


# ── the preamble ──────────────────────────────────────────────────────────────

def f(name="A"):
    return FailureMode(failure_mode=name, attack_chain=["s1"], business_impact="i", blast_radius="b", trigger="t", evidence="a.py:1 `x`")


def risk(name="A"):
    return RiskScore(failure_mode=name, severity=5, occurrence=5, detection=5, rpn=125, priority="High", justification="j",
                     severity_rationale="", occurrence_rationale="", detection_rationale="")


CTX = SystemContext(tiering={}, attack_surfaces=[], failure_domains=[])
CONTROLS = [ControlAssessment(failure_mode="A", controls={}, control_maturity="Low", gaps=[])]


def run_all_agents():
    """Run every model-calling agent once; parsing the fake answers may fail, which does not matter here."""
    calls = [
        lambda: surveyor.run_surveyor("code", business_context="biz"),
        lambda: saboteur.run_saboteur("code", CTX),
        lambda: controls_assessor.run_controls_assessor([f()], "code"),
        lambda: scenario_linkage.run_scenario_linkage([f()], "code"),
        lambda: actuary.score_all_failures([f()], CONTROLS, CTX),
        lambda: sre_agent.run_sre_agent(f(), CONTROLS[0], risk()),
        lambda: validator.run_validator([f()], [risk()]),
        lambda: llm_judge.run_llm_judge([f()], [risk()], [ValidationResult(failure_mode="A")], []),
    ]
    from agents import remediator
    plan = RemediationPlan(failure_mode="A", fixes=["validate input"], monitoring=[], resilience_upgrades=[])
    calls.append(lambda: remediator.generate_fix(f(), plan, "def handler(x):\n    return x\n"))
    for call in calls:
        try:
            call()
        except Exception:
            pass


def test_every_agent_prompt_carries_the_defensive_preamble(monkeypatch):
    rec = Recorder([answer("{}")]).install(monkeypatch)
    run_all_agents()
    assert len(rec.requests) >= 9
    missing = [i for i, r in enumerate(rec.requests) if prompt_context.PREAMBLE not in json.dumps(r["messages"], default=str).replace("\\n", "\n").replace('\\"', '"')]
    assert missing == []


def test_the_chat_system_message_carries_the_preamble(monkeypatch):
    rec = Recorder([answer("fine")]).install(monkeypatch)
    llm.call_chat([{"role": "system", "content": "You are the results assistant."}, {"role": "user", "content": "why?"}])
    system = rec.requests[0]["messages"][0]
    assert system["role"] == "system" and prompt_context.PREAMBLE in system["content"] and "results assistant" in system["content"]
    rec2 = Recorder([answer("fine")]).install(monkeypatch)
    llm.call_chat([{"role": "user", "content": "no system message yet"}])
    assert rec2.requests[0]["messages"][0]["role"] == "system" and prompt_context.PREAMBLE in rec2.requests[0]["messages"][0]["content"]


def test_the_preamble_is_identical_for_every_provider_and_stable_across_turns(monkeypatch):
    seen = []
    for model in ("mistral-large-4", "gpt-5.1"):
        settings.set_setting("active_model", model)
        rec = Recorder([answer("fine")]).install(monkeypatch)
        llm.call_chat([{"role": "system", "content": "S"}, {"role": "user", "content": "q"}])
        llm.call_chat([{"role": "system", "content": "S"}, {"role": "user", "content": "q2"}])
        seen += [r["messages"][0]["content"] for r in rec.requests]
    assert len(set(seen)) == 1


def test_the_preamble_states_the_purpose_honestly_and_asks_for_no_weapons():
    text = prompt_context.PREAMBLE.lower()
    for must in ("defensive", "owns or is authorised", "rank risk", "fix"):
        assert must in text
    assert "do not" in text and "exploit" in text and "payload" in text


# ── wording ───────────────────────────────────────────────────────────────────

BANNED = [r"red[- ]team", r"\belite\b", r"like an attacker", r"planning a real attack", r"\bapt\b", r"adversarial thinker",
          r"maximally adversarial", r"highly adversarial", r"weaponi[sz]", r"working exploit", r"write (an )?exploit"]


def prompt_texts(monkeypatch):
    rec = Recorder([answer("{}")]).install(monkeypatch)
    run_all_agents()
    # the preamble itself forbids exploit code, so it is not part of what is scanned for banned wording
    texts = [json.dumps(r["messages"], default=str).replace(json.dumps(prompt_context.PREAMBLE)[1:-1], "") for r in rec.requests]
    texts += list(__import__("memory.learning_memory", fromlist=["x"])._AGGRESSION_DESCRIPTIONS.values())
    texts.append(chat.SYSTEM_PROMPT)
    return texts


def test_no_prompt_template_casts_the_model_as_an_attacker_or_asks_for_an_exploit(monkeypatch):
    offenders = [(p, t[:80]) for t in prompt_texts(monkeypatch) for p in BANNED if re.search(p, t, re.IGNORECASE)]
    assert offenders == []


def test_the_saboteur_is_an_analyst_and_keeps_its_output_contract(monkeypatch):
    rec = Recorder([answer("[]")]).install(monkeypatch)
    saboteur.run_saboteur("code", CTX, locked_names=["Known"])
    prompt = rec.requests[0]["messages"][-1]["content"]
    assert "analyst" in prompt.lower() and '"attack_chain"' in prompt and '"failure_mode"' in prompt and "Known" in prompt


def test_the_learning_memory_aggression_levels_still_exist_and_are_defensive():
    from memory.learning_memory import _AGGRESSION_DESCRIPTIONS
    assert sorted(_AGGRESSION_DESCRIPTIONS) == [1, 2, 3, 4, 5]
    assert len(set(_AGGRESSION_DESCRIPTIONS.values())) == 5


# ── classification ────────────────────────────────────────────────────────────

def test_a_mistral_guardrail_403_and_an_openai_content_filter_are_provider_blocks():
    assert is_provider_block(mistral_guardrail()) and is_provider_block(openai_filter())
    assert is_provider_block(status_error(openai.BadRequestError, 400, {"error": {"code": "content_policy_violation"}}))
    assert is_provider_block(status_error(openai.PermissionDeniedError, 403, {"message": "blocked", "type": "guardrail_violation"}))


@pytest.mark.parametrize("exc", [
    status_error(openai.AuthenticationError, 401, {"message": "bad key"}),
    status_error(openai.PermissionDeniedError, 403, {"message": "You do not have access to this model"}),
    status_error(openai.RateLimitError, 429, {"message": "slow down"}),
    status_error(openai.BadRequestError, 400, {"error": {"code": "context_length_exceeded"}}),
    status_error(openai.InternalServerError, 500, {"message": "oops"}),
    ValueError("not an api error"),
    openai.APIConnectionError(request=REQUEST),
])
def test_other_errors_are_not_provider_blocks(exc):
    assert is_provider_block(exc) is False


def test_the_llm_layer_raises_provider_blocked_with_provider_model_and_stage(monkeypatch):
    Recorder([mistral_guardrail()]).install(monkeypatch)
    from core.telemetry import agent_span
    with pytest.raises(ProviderBlocked) as exc:
        with agent_span("saboteur"):
            llm.call_llm("prompt")
    blocked = exc.value
    assert (blocked.provider, blocked.model, blocked.stage) == ("mistral", "mistral-large-4", "saboteur")


@pytest.mark.parametrize("response", [answer("", finish="content_filter"), answer("", refusal="I can't help with that.")])
def test_a_filtered_or_refused_answer_is_a_provider_block(monkeypatch, response):
    Recorder([response]).install(monkeypatch)
    with pytest.raises(ProviderBlocked):
        llm.call_llm("prompt")


def test_a_blocked_prompt_is_never_retried_with_the_same_wording(monkeypatch):
    rec = Recorder([mistral_guardrail(), answer("[]")]).install(monkeypatch)
    with pytest.raises(ProviderBlocked):
        llm.call_llm("prompt")
    assert len(rec.requests) == 1
    rec2 = Recorder([answer("", finish="content_filter"), answer("[]")]).install(monkeypatch)
    with pytest.raises(ProviderBlocked):
        llm.call_llm("prompt")
    assert len(rec2.requests) == 1


def test_an_agent_that_falls_back_on_errors_cannot_swallow_a_block(monkeypatch):
    Recorder([mistral_guardrail()]).install(monkeypatch)
    with pytest.raises(ProviderBlocked):
        validator.run_validator([f()], [risk()])
    with pytest.raises(ProviderBlocked):
        llm_judge.run_llm_judge([f()], [risk()], [ValidationResult(failure_mode="A")], [])


def test_a_block_is_counted_in_telemetry_with_its_stage(monkeypatch):
    Recorder([mistral_guardrail()]).install(monkeypatch)
    from core.telemetry import agent_span, set_scan_context
    ws = db.upsert_workspace(NS(customer="c", project="p", function="", business_tier="Tier 1", user_type="x", business_context=""))
    set_scan_context(scan_id=None, workspace_id=ws)
    with pytest.raises(ProviderBlocked):
        with agent_span("actuary"):
            llm.call_llm("prompt")
    conn = db.get_db()
    rows = conn.execute("SELECT agent, error FROM telemetry").fetchall()
    conn.close()
    assert [(r["agent"], r["error"]) for r in rows] == [("actuary", "provider_blocked")]


# ── what the user sees ────────────────────────────────────────────────────────

def blocked_error():
    return ProviderBlocked("mistral", "mistral-large-4", "saboteur")


def test_a_blocked_scan_says_which_provider_and_stage_and_offers_another_model(monkeypatch):
    from api.main import app
    def boom(*a, **k):
        raise blocked_error()
    monkeypatch.setattr("api.routers.scan.run_fmea", boom)
    r = TestClient(app).post("/api/scan", json={"code": "print(1)"})
    frames = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    err = next(x for x in frames if x.get("stage") == "error")
    assert err["code"] == "provider_blocked" and err["action"] == "choose_model"
    assert "Mistral AI" in err["msg"] and "saboteur" in err["msg"] and "another model" in err["msg"]
    assert "guardrail" not in err["msg"].lower() and "403" not in err["msg"]


def test_a_blocked_chat_turn_is_a_chat_error_with_a_plain_message(monkeypatch):
    ws = NS(customer="Acme", project="Pay", function="", business_tier="Tier 1", user_type="x", business_context="", customer_learning=True)
    wid = db.upsert_workspace(ws)
    db.save_scan_snapshot(wid, 1, "fp", {"failures": [{"failure_mode": "A"}], "risks": []}, {"a.py": "x = 1"})
    Recorder([mistral_guardrail()]).install(monkeypatch)
    with pytest.raises(chat.ChatError) as exc:
        chat.chat_turn(wid, "How is it exploited?")
    assert exc.value.code == "provider_blocked" and "Mistral AI" in exc.value.message and "another model" in exc.value.message
    from api.routers.chat import _STATUS
    assert _STATUS["provider_blocked"] == 409


def test_the_pipeline_result_records_model_and_provider(monkeypatch, tmp_path):
    from test_finding_lifecycle import Harness, failure
    harness = Harness(monkeypatch, tmp_path)
    result = harness.scan([failure("A")])
    assert result["model"] == "mistral-large-4" and result["provider"] == "mistral"


def test_a_blocked_pull_request_check_is_a_plain_error(monkeypatch, tmp_path):
    from core import pr_check
    from test_pr_check import PrHarness
    from test_finding_lifecycle import failure
    import workflows.fmea_pipeline as pipeline
    ph = PrHarness(monkeypatch, tmp_path)
    ph.baseline([failure("A")])

    def boom(*a, **k):
        raise blocked_error()

    monkeypatch.setattr(pipeline, "run_saboteur", boom)
    with pytest.raises(pr_check.PrCheckError) as exc:
        ph.check([failure("A")])
    assert exc.value.status == 502 and "Mistral AI" in str(exc.value) and "another model" in str(exc.value)


# ── the benchmark ─────────────────────────────────────────────────────────────

def test_the_benchmark_records_blocked_scans_and_the_report_shows_the_block_rate(tmp_path):
    from benchmarks import run as bench
    from benchmarks.report import format_table, summarise
    repo = bench.REPOS_DIR / "notes-express"

    def blocked_fmea(code, **kw):
        raise blocked_error()

    one = bench.run_once(repo, "mistral-large-4", "off", 1, {}, run_fmea=blocked_fmea)
    assert one["blocked"] is True and "provider_blocked" in one["error"] and one["findings"] == []
    ok = {"findings": [], "error": None, "cost_usd": 0.1, "seconds": 1, "llm_calls": 3}
    result = {"meta": {"label": "t", "model": "mistral-large-4", "reasoning": "off", "runs": 2, "created": "now", "signed_off": {}},
              "repos": {"notes-express": {"runs": [one, ok]}}}
    summary = summarise(result)
    assert summary["overall"]["runs_blocked"] == 1 and summary["overall"]["block_rate"] == 0.5
    table = format_table([summary])
    assert "blocked: 1 of 2" in table.lower()


# ── review follow-ups ─────────────────────────────────────────────────────────

def test_the_learning_context_the_pipeline_really_uses_is_defensive_too():
    import memory.workspace_store as workspace_store
    source = open(workspace_store.__file__, encoding="utf-8").read()
    offenders = [p for p in BANNED if re.search(p, source, re.IGNORECASE)]
    assert offenders == [] and not re.search(r"single high-impact exploit|probe aggressively|attack chain patterns", source, re.IGNORECASE)
    assert sorted(workspace_store._AGGRESSION_DESCRIPTIONS) == [1, 2, 3, 4, 5]


def test_more_real_provider_shapes_are_blocks_and_a_quoted_filter_word_in_a_server_error_is_not():
    assert is_provider_block(status_error(openai.BadRequestError, 400, {"error": {"code": "invalid_prompt",
                             "message": "Your prompt was flagged as potentially violating our usage policy."}}))
    assert not is_provider_block(status_error(openai.InternalServerError, 500, {"message": "upstream said content_filter"}))
    assert is_provider_block(openai.APIError("blocked", request=REQUEST, body={"code": "content_filter", "message": "x"}))


class FakeStream:
    def __init__(self, chunks, error=None):
        self.chunks, self.error = chunks, error

    def __iter__(self):
        yield from self.chunks
        if self.error:
            raise self.error

    def close(self):
        pass


def delta(content=None, refusal=None, finish=None):
    return NS(usage=None, choices=[NS(finish_reason=finish, delta=NS(content=content, tool_calls=None, refusal=refusal))])


def test_a_mid_stream_error_event_a_stream_refusal_and_a_stream_filter_are_blocks(monkeypatch):
    errors = openai.APIError("blocked", request=REQUEST, body={"code": "content_filter"})
    for stream in (FakeStream([delta("par")], error=errors), FakeStream([delta(refusal="I cannot help")]),
                   FakeStream([delta("x"), delta(finish="content_filter")])):
        Recorder([stream]).install(monkeypatch)
        with pytest.raises(ProviderBlocked):
            list(llm.stream_chat([{"role": "system", "content": "S"}, {"role": "user", "content": "q"}]))


def test_the_usage_of_a_blocked_stream_is_still_recorded(monkeypatch):
    Recorder([FakeStream([delta("x"), delta(finish="content_filter")])]).install(monkeypatch)
    llm.reset_call_count()
    with pytest.raises(ProviderBlocked):
        list(llm.stream_chat([{"role": "user", "content": "q"}]))
    assert llm.get_call_count() == 1


def test_a_block_while_folding_old_chat_history_is_a_chat_error(monkeypatch):
    ws = NS(customer="Acme", project="Pay", function="", business_tier="Tier 1", user_type="x", business_context="", customer_learning=True)
    wid = db.upsert_workspace(ws)
    db.save_scan_snapshot(wid, 1, "fp", {"failures": [{"failure_mode": "A"}], "risks": []}, {"a.py": "x = 1"})
    monkeypatch.setattr(chat, "_fold_old_history", lambda thread, rows: (_ for _ in ()).throw(blocked_error()))
    with pytest.raises(chat.ChatError) as exc:
        chat.prepare_turn(wid, "hello again")
    assert exc.value.code == "provider_blocked"


def test_benchmark_runs_stored_before_the_flag_existed_count_as_blocked_from_the_providers_error(tmp_path):
    from benchmarks.report import is_blocked_run
    assert is_blocked_run({"error": "PermissionDeniedError: Error code: 403 - Request blocked by guardrail policy (code 1920)"})
    assert is_blocked_run({"blocked": True, "error": "x"}) and not is_blocked_run({"error": "RuntimeError: cut off"}) and not is_blocked_run({"error": None})
