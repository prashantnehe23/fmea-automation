import json

from core.llm import call_llm, extract_json_text
from core.llm_coercion import coerce_saboteur_json_root
from core.models import FailureMode, SystemContext


def run_saboteur(
    code: str,
    context: SystemContext,
    *,
    max_scenarios: int | None = None,
    learning_context: str = "",
    locked_names: list[str] | None = None,
    previous_names: list[str] | None = None,
) -> list[FailureMode]:
    cap_line = ""
    if max_scenarios is not None:
        cap_line = (
            f"\nReturn at most {max_scenarios} failure scenarios "
            f"(JSON array length <= {max_scenarios}). Prioritise the highest-impact scenarios.\n"
        )

    learning_block = (
        f"\n{learning_context}\n" if learning_context.strip() else ""
    )

    # Scenario-continuity constraint: reproduce locked names verbatim
    lock_block = ""
    if locked_names:
        names_list = "\n".join(f"- {n}" for n in locked_names)
        lock_block = f"""
IMPORTANT — SCENARIO CONTINUITY:
These scenarios were found in earlier scans. For each one whose weakness is still present in the code below,
reproduce it by its EXACT name (copy verbatim). If its weakness has been fixed or removed so that it no longer
applies to this code, leave it out: never repeat a scenario that no longer applies.
Locked scenarios do not count against the cap: always report every NEW scenario you find in addition to them.

Earlier scenarios:
{names_list}

"""

    if previous_names:
        previous_list = "\n".join(f"- {n}" for n in previous_names)
        lock_block += f"""
These scenarios were fixed in the past, or may have been. Report one only if its weakness is present in the code
below, using its EXACT name; otherwise leave it out.
{previous_list}

"""

    prompt = f"""
{lock_block}{learning_block}
You are an elite red team operative — an adversarial thinker who reasons like an attacker
planning a real attack on a live production system.

Use chain-of-thought reasoning. For EACH failure scenario, work through these steps
explicitly in your head before writing the output:

  STEP 1 — Entry point: What interface, input vector, or trust boundary can be abused?
            (API endpoint, file upload, config value, external dependency, shared resource)
  STEP 2 — Attack path: What sequence of actions does an attacker (or a fault) take?
            Be specific — name the functions, data flows, or state transitions involved.
  STEP 3 — Failure condition: What breaks, corrupts, leaks, or gets bypassed?
            What is the exact technical failure (race window, missing validation,
            exposed secret, auth bypass, cascading error)?
  STEP 4 — Business impact: Which business operations are affected?
            Who is harmed — customers, operations staff, the business itself?
            Can this failure enable lateral movement to adjacent systems?
  STEP 5 — Trigger: What specific action, input, or condition fires this scenario?
            Is it a crafted request, a timing window, a configuration state,
            a concurrent operation, or an automated tool scan?

System cartography (output of the surveyor):
{context.model_dump_json()}

Code:
{code}
{cap_line}
Attack vectors to explore (cover as many as are genuinely applicable):
- Concurrency and race conditions (TOCTOU, double-spend, parallel state mutation)
- Partial failures and cascading effects (one component fails, what else breaks?)
- Malicious or malformed input (injection, boundary values, type confusion, fuzzing)
- Secrets and credential exposure (hardcoded keys, leaked tokens, insecure storage)
- Authentication and authorisation bypass (missing checks, privilege escalation,
  token reuse, session fixation)

Return a JSON array of failure scenario objects — no wrapper object, array only.
Each object must have these fields:
  "failure_mode"    : string  — concise name of the failure
  "attack_chain"    : array of strings — each step in the attack sequence (from STEP 2)
  "business_impact" : string  — business operations affected and who is harmed
  "blast_radius"    : string  — scope and propagation of damage
  "trigger"         : string  — specific condition or action that fires this scenario
  "evidence"        : string  — path:line references from the numbered code plus a short quote of the code (""  only if no code supports it)
"""

    response = call_llm(prompt, max_tokens=8192)
    root = json.loads(extract_json_text(response))
    items = coerce_saboteur_json_root(root)
    return [FailureMode(**item) for item in items]
