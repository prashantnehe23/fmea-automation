"""
Human-in-the-loop: relate each failure scenario to code themes (e.g. concurrency vs secrets)
and to other scenarios (e.g. zero-amount transfer vs race on balance).
"""

import json

from core.llm import call_llm, extract_json_text
from core.models import FailureMode, ScenarioExplanation, ScenarioLinkageReport


def _coerce_linkage(raw: object) -> ScenarioLinkageReport:
    if not isinstance(raw, dict):
        raw = {}
    expl_raw = raw.get("explanations") or raw.get("scenario_explanations") or []
    if isinstance(expl_raw, dict):
        expl_raw = list(expl_raw.values())
    out: list[ScenarioExplanation] = []
    for item in expl_raw:
        if not isinstance(item, dict):
            continue
        fm = str(item.get("failure_mode") or item.get("failureMode") or "").strip()
        if not fm:
            continue
        out.append(
            ScenarioExplanation(
                failure_mode=fm,
                scenario_summary=str(
                    item.get("scenario_summary")
                    or item.get("summary")
                    or "Scenario summary not provided."
                )[:500],
                code_connection=str(
                    item.get("code_connection")
                    or item.get("code_and_themes")
                    or item.get("themes")
                    or "Link to code not specified."
                )[:800],
                links_to_other_scenarios=str(
                    item.get("links_to_other_scenarios")
                    or item.get("related_scenarios")
                    or item.get("relationships")
                    or "See other scenarios in this assessment."
                )[:800],
            )
        )
    themes = raw.get("cross_cutting_themes") or raw.get("themes_summary") or ""
    if isinstance(themes, list):
        themes = "; ".join(str(x) for x in themes)
    return ScenarioLinkageReport(
        explanations=out,
        cross_cutting_themes=str(themes)[:2000],
    )


def run_scenario_linkage(failures: list[FailureMode], code: str) -> ScenarioLinkageReport:
    if not failures:
        return ScenarioLinkageReport(explanations=[], cross_cutting_themes="")

    summaries = [
        {
            "failure_mode": f.failure_mode,
            "attack_chain": f.attack_chain,
            "business_impact": f.business_impact,
            "trigger": f.trigger,
        }
        for f in failures
    ]
    prompt = f"""
You validate how failure scenarios relate to the code and to each other (human review aid).

Code (excerpt may be truncated in UI; reason from structure):
---
{code[:12000]}
---

Failure scenarios (JSON):
{json.dumps(summaries, indent=2)}

Return JSON only with:
- "explanations": array of one object per failure_mode above, each with:
  - "failure_mode": exact same string as input
  - "scenario_summary": ONE concise sentence describing the scenario risk
  - "code_connection": ONE or TWO sentences naming concrete themes in the code (e.g. in-memory wallet + sleep enabling races, hardcoded API key, missing validation on transfer, concurrency on /transfer)
  - "links_to_other_scenarios": ONE sentence explaining how this scenario connects to others (e.g. zero-amount or negative transfer abuse relates to the same race/validation gaps as double-spend)
- "cross_cutting_themes": ONE short paragraph listing themes spanning scenarios (concurrency, secrets, input validation, etc.)

Be explicit when linking validation/abuse cases to race/concurrency issues where applicable.
"""
    try:
        response = call_llm(prompt, max_tokens=6000)
        raw = json.loads(extract_json_text(response))
        report = _coerce_linkage(raw)
    except Exception:
        report = ScenarioLinkageReport(explanations=[], cross_cutting_themes="")

    known = {e.failure_mode.strip().lower(): e for e in report.explanations}
    merged: list[ScenarioExplanation] = []
    for f in failures:
        key = f.failure_mode.strip().lower()
        if key in known:
            merged.append(known[key])
        else:
            merged.append(
                ScenarioExplanation(
                    failure_mode=f.failure_mode,
                    scenario_summary=(
                        (f.business_impact[:200] + "…")
                        if len(f.business_impact) > 200
                        else f.business_impact
                    ),
                    code_connection="Review attack_chain and trigger against the source code for concrete themes.",
                    links_to_other_scenarios="Compare with other scenarios sharing validation, auth, or concurrency patterns.",
                )
            )
    themes = report.cross_cutting_themes or ""
    if not themes.strip():
        themes = (
            "Themes often cluster around authentication material, input validation, and "
            "concurrency on shared mutable state—compare scenarios that reference the same endpoints."
        )
    return ScenarioLinkageReport(explanations=merged, cross_cutting_themes=themes)
