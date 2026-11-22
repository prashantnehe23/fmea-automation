"""B-030 (ADR-018): the preventive agent. Stops this class of weakness from coming back, shaped by its root cause."""

import json

from core.actions import PREVENTIVE_KINDS, coerce_actions
from core.llm import call_llm, extract_json_text
from core.models import Action, ControlAssessment, FailureMode, RiskScore

# root-cause domain -> (default kind, what to focus on)
_FOCUS = {
    "architectural": ("design_change", "Prefer design_change actions: change the design so the weakness cannot arise, such as isolating components, removing shared state or narrowing trust boundaries."),
    "operational": ("monitoring", "Prefer monitoring and runbook actions: detect the condition early and write down how to respond to it."),
    "engineering": ("guardrail", "Prefer guardrail actions: tests, lint rules, code review checks and safe library defaults that catch this mistake before it ships."),
    "security": ("guardrail", "Prefer guardrail actions that enforce the security control by default, with monitoring to detect misuse."),
}
_GENERAL = "Choose the mix of kinds that best stops this class of weakness from returning. First decide whether its root cause is architectural, operational, engineering or security, and let that shape the actions."


def run_preventive_agent(failure: FailureMode, control: ControlAssessment, risk: RiskScore,
                         domain: str | None = None) -> list[Action]:
    default_kind, focus = _FOCUS.get(str(domain or "").lower(), (None, _GENERAL))
    prompt = f"""
You are a senior engineer planning the preventive actions for one weakness found in code you are authorised to assess.
Preventive means: stop this class of weakness from coming back or going unnoticed. The corrective actions are planned separately.

Failure:
{failure.model_dump_json()}

Control gaps:
{json.dumps(control.gaps)}

Risk scoring:
{risk.model_dump_json()}

Give 2 to 4 actions. Each action is a JSON object with:
- title: short imperative sentence
- detail: one or two sentences saying what to put in place and how
- kind: one of {", ".join(PREVENTIVE_KINDS)}
- target: the pipeline, component, service or document it applies to
- verification: how a reviewer proves the action is working
- owner_role: one of developer, security, sre, product

Do not give dates, durations or schedules. Leave out working attack code and ready-made payloads.

Return JSON only: {{"actions": [ ... ]}}

Focus for this failure: {focus}
"""
    response = call_llm(prompt, max_tokens=4096)
    try:
        raw = json.loads(extract_json_text(response))
    except (json.JSONDecodeError, ValueError):
        return []
    return coerce_actions(raw, side="preventive", failure=failure, risk=risk, default_kind=default_kind)
