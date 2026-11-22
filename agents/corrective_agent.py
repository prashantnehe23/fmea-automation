"""B-030 (ADR-018): the corrective agent. Fixes the failure that exists now: stop it, repair it, prove the repair."""

import json

from core.actions import CORRECTIVE_KINDS, coerce_actions
from core.llm import call_llm, extract_json_text
from core.models import Action, ControlAssessment, FailureMode, RiskScore


def run_corrective_agent(failure: FailureMode, control: ControlAssessment, risk: RiskScore) -> list[Action]:
    prompt = f"""
You are a senior engineer planning the corrective actions for one weakness found in code you are authorised to assess.
Corrective means: fix what is wrong now, or contain it while the fix is made.

Failure:
{failure.model_dump_json()}

Control gaps:
{json.dumps(control.gaps)}

Risk scoring:
{risk.model_dump_json()}

Give 2 to 4 actions. Each action is a JSON object with:
- title: short imperative sentence
- detail: one or two sentences saying what to change and how
- kind: one of {", ".join(CORRECTIVE_KINDS)}
- target: the file, function, service or setting it changes (use the file named in the failure's evidence when there is one)
- verification: how a reviewer proves the action worked, such as a test that fails before and passes after
- owner_role: one of developer, security, sre, product

Do not give dates, durations or schedules. Leave out working attack code and ready-made payloads.

Return JSON only: {{"actions": [ ... ]}}
"""
    response = call_llm(prompt, max_tokens=4096)
    try:
        raw = json.loads(extract_json_text(response))
    except (json.JSONDecodeError, ValueError):
        return []
    return coerce_actions(raw, side="corrective", failure=failure, risk=risk)
