"""B-030 (ADR-018): one remediation plan per finding, from two agents that run side by side."""

import contextvars
from concurrent.futures import ThreadPoolExecutor

from agents.corrective_agent import run_corrective_agent
from agents.preventive_agent import run_preventive_agent
from core.llm import _current_usage
from core.models import ControlAssessment, FailureMode, RemediationPlan, RiskScore


def _actions(future) -> list:
    """An ordinary failure of one agent leaves that side empty (the evaluator reports it) and keeps the other side.
    A provider block or spend limit is a BaseException and still propagates."""
    try:
        return future.result()
    except Exception:
        return []


def run_sre_agent(
    failure: FailureMode,
    control: ControlAssessment,
    risk: RiskScore,
    domain: str | None = None,
) -> RemediationPlan:
    # Each worker runs in a copy of this context so that usage, budget and stage tracking reach the scan.
    # A provider block or spend limit raised in either worker propagates from result().
    _current_usage()                       # make sure the scan's counter exists before the workers copy the context
    with ThreadPoolExecutor(max_workers=2) as pool:
        corrective = pool.submit(contextvars.copy_context().run, run_corrective_agent, failure, control, risk)
        preventive = pool.submit(contextvars.copy_context().run, run_preventive_agent, failure, control, risk, domain)
        return RemediationPlan(failure_mode=failure.failure_mode,
                               corrective=_actions(corrective), preventive=_actions(preventive))
