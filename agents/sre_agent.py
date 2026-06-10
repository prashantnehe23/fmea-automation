import json



from core.llm import call_llm, extract_json_text

from core.llm_coercion import coerce_remediation_plan_payload

from core.models import ControlAssessment, FailureMode, RemediationPlan, RiskScore





def run_sre_agent(

    failure: FailureMode,

    control: ControlAssessment,

    risk: RiskScore,

) -> RemediationPlan:

    prompt = f"""

You are an SRE engineer planning implementation-ready remediation.



Failure:

{failure.model_dump_json()}



Control gaps:

{json.dumps(control.gaps)}



Risk scoring (use RPN to prioritize urgency — higher RPN = more expedited workstreams):

{risk.model_dump_json()}



Produce:

1) fixes, monitoring, resilience_upgrades as actionable bullet strings.

2) roadmap_90_day: keys "Day 30", "Day 60", "Day 90" with short paragraphs; higher RPN should front-load heavier mitigation in Day 30.

3) roadmap_tasks: 4–8 implementation tasks as a Gantt-friendly list. Each task:

   - task_id: short slug (e.g. t1_validate_transfer)

   - title: short

   - start_day, end_day: integers 1–90 within the phase

   - depends_on: array of task_ids that must finish first (empty if none)

   - expedited: true if this scenario's RPN is Critical/High and task is on critical path

   - implementation_note: one sentence (dependencies, owners, or rollout order)

4) dependency_notes: one paragraph on how tasks depend on each other and sequencing.

5) rpn_priority_note: one sentence on how this scenario's RPN drove ordering vs. longer-lead items.



Return JSON only with keys:

failure_mode, fixes, monitoring, resilience_upgrades, roadmap_90_day,

roadmap_tasks, dependency_notes, rpn_priority_note

"""



    response = call_llm(prompt, max_tokens=8192)

    try:
        raw = json.loads(extract_json_text(response))
    except json.JSONDecodeError:
        # Graceful fallback: return a minimal plan rather than crashing the scan
        raw = {
            "failure_mode": failure.failure_mode,
            "fixes": ["Manual remediation required — SRE plan could not be parsed."],
            "monitoring": [],
            "resilience_upgrades": [],
            "roadmap_90_day": {},
            "roadmap_tasks": [],
            "dependency_notes": "",
            "rpn_priority_note": "",
        }

    payload = coerce_remediation_plan_payload(
        raw, failure_mode_hint=failure.failure_mode, risk=risk
    )

    return RemediationPlan(**payload)

