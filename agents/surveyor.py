import json

from core.llm import call_llm, extract_json_text
from core.models import SystemContext
from core.untrusted import as_data_block


def run_surveyor(code: str, business_context: str = "") -> SystemContext:
    _biz_block = (
        "Business context:\n" + as_data_block("business_context", business_context) + "\n"
        "Use this to inform component tiering — Tier 1 is business-critical to this context.\n\n"
        if as_data_block("business_context", business_context) else ""
    )
    prompt = f"""{_biz_block}
You are a system cartographer. Use a Tree of Thoughts approach: explore three independent
analytical perspectives on the code, then synthesize into a final cartography.

--- PERSPECTIVE 1: Attack Surface View ---
Examine all external entry points, interfaces, and trust boundaries.
Which components accept input from outside the system? Where does untrusted data enter?
What APIs, endpoints, file reads, or external calls exist?
What authentication or authorisation gates are present (or absent)?

--- PERSPECTIVE 2: Data Criticality View ---
Examine what data the system holds, processes, or transmits.
Which operations touch financial, personal, credential, or business-critical data?
If each component failed or was compromised, what is the business consequence?
Use this to assign tiers:
  Tier 1 = mission-critical (failure = business stoppage, data loss, or regulatory breach)
  Tier 2 = important (failure = degraded service or significant customer impact)
  Tier 3 = supporting (failure = inconvenience, no direct business-critical consequence)

--- PERSPECTIVE 3: Dependency and Blast Radius View ---
Examine how components depend on each other.
If one component fails or is compromised, which others are affected?
What is the propagation path? Are there shared databases, caches, queues, or auth tokens
that multiple components rely on?

--- SYNTHESIS ---
Combine all three perspectives into a unified cartography. Assign each component/path a
tier that reflects BOTH its data criticality AND its position in the dependency graph.
An internally-facing component that holds credentials or sits on a critical data path
should be rated Tier 1 or Tier 2 even if it has no direct external interface.

Code:
{code}

Return JSON only — no explanation outside the JSON:
{{
  "tiering": {{
    "<component or path>": "<Tier 1 | Tier 2 | Tier 3>",
    ...
  }},
  "attack_surfaces": [
    "<description of external entry point or trust boundary>",
    ...
  ],
  "failure_domains": [
    "<description of blast-radius zone or dependency chain>",
    ...
  ]
}}
"""

    response = call_llm(prompt)
    return SystemContext(**json.loads(extract_json_text(response)))
