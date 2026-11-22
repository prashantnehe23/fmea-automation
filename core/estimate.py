"""
core/estimate.py — B-028 phase 0: what a scan will roughly cost, shown before it starts.

A scan makes four model calls per batch of code (surveyor, saboteur, controls, linkage), shared calls
(actuary, validator, judge, in chunks of ten findings) and two remediation calls per finding (corrective and preventive), up to a per-scan
limit. The number of findings is not known in advance, so seven per batch (the old cap) is the planning
figure and the limit gives the upper figure. It is an estimate, never a promise; real cost is recorded per scan (B-021).
"""

from __future__ import annotations

import math

from core.costs import compute_cost, rates_known
from core.llm import get_model_name
from workflows.fmea_pipeline import AGENT_CHUNK, MAX_REMEDIATION_PLANS

CALLS_PER_BATCH = 4
SHARED_CALLS = 4                    # actuary, root cause, validator, judge
REMEDIATION_CALLS_PER_FINDING = 2   # corrective and preventive agents (B-030)
FINDINGS_PER_BATCH = 7
TOKENS_PER_BYTE = 0.25          # about four characters per token
OVERHEAD_TOKENS = 1500          # instructions and context per call
SHARED_PROMPT_TOKENS = 3000
REMEDIATION_PROMPT_TOKENS = 2500
COMPLETION_TOKENS_PER_CALL = 1500


def _tokens(batch_bytes: list[int], findings: int) -> tuple[int, int, int]:
    if not batch_bytes:
        return 0, 0, 0
    shared = SHARED_CALLS * max(1, math.ceil(findings / AGENT_CHUNK))        # actuary and validator run in chunks
    calls = CALLS_PER_BATCH * len(batch_bytes) + shared + findings * REMEDIATION_CALLS_PER_FINDING
    prompt = sum(CALLS_PER_BATCH * (int(size * TOKENS_PER_BYTE) + OVERHEAD_TOKENS) for size in batch_bytes)
    prompt += shared * SHARED_PROMPT_TOKENS + findings * REMEDIATION_CALLS_PER_FINDING * REMEDIATION_PROMPT_TOKENS
    return calls, prompt, calls * COMPLETION_TOKENS_PER_CALL


def estimate_scan(batch_bytes: list[int]) -> dict:
    """
    Calls, tokens and USD for a scan whose batches have the given sizes in bytes. `usd` assumes the planning
    figure of findings; `usd_max` assumes the most remediation plans a scan will make (the spend guard), so
    the real cost should fall between them unless retries or continuations add calls.
    """
    model = get_model_name()
    typical = min(FINDINGS_PER_BATCH * len(batch_bytes), MAX_REMEDIATION_PLANS)
    calls, prompt, completion = _tokens(batch_bytes, typical)
    _, max_prompt, max_completion = _tokens(batch_bytes, MAX_REMEDIATION_PLANS)
    _, single_prompt, single_completion = _tokens(batch_bytes[:1], min(FINDINGS_PER_BATCH, MAX_REMEDIATION_PLANS))
    return {
        "model": model,
        "rates_known": rates_known(model),
        "batches": len(batch_bytes),
        "calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "usd": compute_cost(model, prompt, completion),
        "usd_max": compute_cost(model, max_prompt, max_completion),
        "single_pass_usd": compute_cost(model, single_prompt, single_completion),
        "exceeds_single_pass": len(batch_bytes) > 1,
    }
