"""
agents/remediator.py — Auto-remediation agent.

Given a failure mode and its SRE remediation plan, generates:
  1. code_diff   — unified diff showing the proposed code change
  2. test_code   — pytest test stub to validate the fix
  3. test_description — plain-English what the test verifies
  4. patched_snippet — complete fixed function/block (valid Python)

apply_and_rescan() applies all fixes in-memory (descending RPN order),
runs run_fmea() on the patched code, and returns before/after RPN deltas.
"""

from __future__ import annotations

import json
import re

from core.actions import plan_actions
from core.llm import call_llm, extract_json_text
from core.models import FailureMode, RemediationPlan, RemediationResult, RiskScore


# ── Single-scenario fix generation ────────────────────────────────────────────

def _extract_relevant_code(code: str, failure: FailureMode) -> str:
    """
    Heuristic: extract up to 60 lines of code most relevant to this failure.
    Searches for function/class names mentioned in evidence and trigger text.
    Falls back to first 60 lines if nothing specific found.
    """
    hints: list[str] = []
    for src in [failure.evidence or "", failure.trigger or ""]:
        # Extract words that look like function or variable names
        hints.extend(re.findall(r'\b([a-z_][a-z0-9_]{2,})\b', src.lower()))

    lines = code.splitlines()
    best_start = 0
    best_score = 0
    window = 60

    for i, line in enumerate(lines):
        score = sum(1 for h in hints if h in line.lower())
        if score > best_score:
            best_score = score
            best_start = max(0, i - 5)

    return "\n".join(lines[best_start: best_start + window])


def generate_fix(
    failure: FailureMode,
    plan: RemediationPlan,
    code: str,
    action_id: str | None = None,
) -> RemediationResult:
    """
    LLM call: generate a code diff, test stub, and patched function for this failure.
    Returns a RemediationResult with before_rpn=0 (caller fills it in).
    """
    relevant = _extract_relevant_code(code, failure)
    corrective, preventive = plan_actions(plan)
    chosen = [a for a in corrective + preventive if a.id == action_id] if action_id else []      # B-053: the action the person chose
    top_fixes = [{"title": a.title, "detail": a.detail, "target": a.target, "verification": a.verification}
                 for a in (chosen or [a for a in corrective if a.kind == "code_fix"] or corrective)[:3]]

    prompt = f"""
You are a senior security engineer implementing a fix for a known vulnerability.

=== FAILURE MODE ===
{failure.model_dump_json(indent=2)}

=== TOP FIXES TO IMPLEMENT ===
{json.dumps(top_fixes, indent=2)}

=== RELEVANT CODE SECTION ===
```python
{relevant}
```

=== TASK ===
Implement the highest-priority fix from the list above.

Return a JSON object with exactly these keys:
{{
  "code_diff": "<unified diff string showing before/after, starting with --- original and +++ patched>",
  "test_code": "<complete pytest test function (import statements + def test_...) that validates the fix>",
  "test_description": "<one sentence: what the test verifies and why it proves the fix works>",
  "patched_snippet": "<the COMPLETE fixed function or class as valid Python — not a partial diff, the full replacement>"
}}

Rules:
- patched_snippet must be a complete, runnable Python function or class (not a fragment).
- test_code must be a standalone pytest test that can be pasted into a test file and run.
- code_diff lines starting with - are removed, lines starting with + are added.
- Return only the JSON object — no explanation outside it.
"""

    response = call_llm(prompt, max_tokens=4000)
    raw = json.loads(extract_json_text(response))

    return RemediationResult(
        failure_mode=failure.failure_mode,
        before_rpn=0,        # caller fills this in
        after_rpn=0,
        rpn_delta=0,
        code_diff=str(raw.get("code_diff", "")),
        test_code=str(raw.get("test_code", "")),
        test_description=str(raw.get("test_description", "")),
        patched_snippet=str(raw.get("patched_snippet", "")),
        applied=False,
    )


# ── Code patching ──────────────────────────────────────────────────────────────

def _extract_func_name(snippet: str) -> str | None:
    """Return the first function/method name defined in snippet."""
    m = re.search(r'^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)', snippet, re.MULTILINE)
    return m.group(1) if m else None


def _apply_patch(code: str, patched_snippet: str) -> str:
    """
    Replace the original function body in code with patched_snippet.
    Matches by function name; replaces from the def line to the next
    top-level def/class at the same or lower indentation level.
    Falls back to appending if the function is not found.
    """
    func_name = _extract_func_name(patched_snippet)
    if not func_name:
        return code + "\n\n" + patched_snippet

    pattern = re.compile(
        r'^((?:async\s+)?def\s+' + re.escape(func_name) + r'\b.*)',
        re.MULTILINE,
    )
    match = pattern.search(code)
    if not match:
        return code + "\n\n" + patched_snippet

    start = match.start()
    # Find where the function ends: next top-level def/class (no leading whitespace)
    rest = code[match.end():]
    end_match = re.search(r'\n(?=(?:async\s+)?def\s|class\s|\Z)', rest)
    if end_match:
        end = match.end() + end_match.start()
    else:
        end = len(code)

    return code[:start] + patched_snippet.rstrip() + "\n" + code[end:]


# ── Batch apply + rescan ───────────────────────────────────────────────────────

def apply_and_rescan(
    failures: list[FailureMode],
    plans: list[RemediationPlan],
    risks: list[RiskScore],
    original_code: str,
    workspace=None,
) -> list[RemediationResult]:
    """
    For each failure mode (sorted by RPN descending):
      1. Generate a fix via LLM.
      2. Apply the patched_snippet into the accumulated code string.
    Then run the full FMEA pipeline on the patched code.
    Match before/after RPNs by failure_mode name.

    Returns one RemediationResult per failure mode (in original order).
    """
    from workflows.fmea_pipeline import run_fmea

    # Sort by RPN descending for application order
    indexed = sorted(
        enumerate(zip(failures, plans, risks)),
        key=lambda x: -x[1][2].rpn,
    )

    remediation_map: dict[str, RemediationResult] = {}
    patched_code = original_code

    for orig_idx, (failure, plan, risk) in indexed:
        try:
            result = generate_fix(failure, plan, patched_code)
            result = result.model_copy(update={
                "before_rpn": risk.rpn,
                "applied": True,
            })
            if result.patched_snippet:
                patched_code = _apply_patch(patched_code, result.patched_snippet)
        except Exception as exc:
            result = RemediationResult(
                failure_mode=failure.failure_mode,
                before_rpn=risk.rpn,
                after_rpn=risk.rpn,
                rpn_delta=0,
                code_diff=f"# Fix generation failed: {exc}",
                test_code="# Fix generation failed",
                test_description="Fix generation failed",
                patched_snippet="",
                applied=False,
            )
        remediation_map[failure.failure_mode] = result

    # Rescan patched code
    try:
        new_result = run_fmea(patched_code, force_rerun=True, workspace=workspace)
        new_rpns: dict[str, int] = {
            r.failure_mode: r.rpn for r in new_result.get("risks", [])
        }
    except Exception:
        new_rpns = {}

    # Fill in after_rpn and rpn_delta
    final: list[RemediationResult] = []
    for failure, _, risk in [t for _, t in sorted(indexed, key=lambda x: x[0])]:
        res = remediation_map.get(failure.failure_mode)
        if res is None:
            res = RemediationResult(
                failure_mode=failure.failure_mode,
                before_rpn=risk.rpn,
            )
        after = new_rpns.get(failure.failure_mode, risk.rpn)
        res = res.model_copy(update={
            "after_rpn": after,
            "rpn_delta": res.before_rpn - after,
        })
        final.append(res)

    # Return in original order (failures list order)
    name_to_result = {r.failure_mode: r for r in final}
    return [name_to_result.get(f.failure_mode, RemediationResult(
        failure_mode=f.failure_mode, before_rpn=r.rpn
    )) for f, r in zip(failures, risks)]
