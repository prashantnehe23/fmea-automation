import json

from core.llm import call_llm, extract_json_text
from core.llm_coercion import coerce_control_assessment_payload
from core.models import ControlAssessment, FailureMode


def run_controls_assessor(
    failures: list[FailureMode], code: str
) -> list[ControlAssessment]:
    """
    Assess controls for all failure modes in a single batched LLM call.
    Returns one ControlAssessment per failure, in the same order.
    """
    failures_json = json.dumps(
        [{"failure_mode": f.failure_mode, "trigger": f.trigger, "blast_radius": f.blast_radius}
         for f in failures],
        indent=2,
    )

    prompt = f"""
You are a resilience auditor. Assess each failure mode below against the codebase.

Code:
{code}

Failure modes to assess (in order):
{failures_json}

Return a JSON array of {len(failures)} control assessment objects, one per failure mode,
in the SAME ORDER as the input list.

Each object must have exactly these keys:
- "failure_mode": string — must exactly match the failure_mode from the input
- "controls": object with string keys and string values (one sentence per control describing what is in place)
- "control_maturity": string — one of "low", "moderate", or "high"
- "gaps": array of strings — specific gaps or missing controls for this failure

Assume basic logging, no chaos testing, limited automation unless the code shows otherwise.
Return only the JSON array — no explanation outside the array.
"""

    response = call_llm(prompt, max_tokens=6000)
    raw = json.loads(extract_json_text(response))

    # Normalise to list
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        raw = [raw]

    # Index by failure_mode for robust ordering (LLM may reorder)
    by_fm: dict[str, dict] = {}
    for item in raw:
        if isinstance(item, dict):
            key = str(item.get("failure_mode", "")).strip()
            if key:
                by_fm[key] = item

    results: list[ControlAssessment] = []
    for f in failures:
        item = by_fm.get(f.failure_mode) or (raw[len(results)] if len(results) < len(raw) else {})
        payload = coerce_control_assessment_payload(item, failure_mode_hint=f.failure_mode)
        results.append(ControlAssessment(**payload))

    return results
