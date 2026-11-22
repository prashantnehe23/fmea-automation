"""
core/budget.py — B-012: a USD limit for one piece of work (a pull-request check).

Inside `spend_limit(usd)` every model call adds its cost to a tracker. Once the limit is reached the call
that crossed it raises BudgetReached, and no further call is started. So the limit can be exceeded by
at most the one call in flight when it was reached, never by a second one.
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager

from core.costs import compute_cost


class BudgetReached(BaseException):
    """The spend limit was reached; the work stops and says so.

    A BaseException on purpose: agents catch Exception to fall back when a model call fails, and a fallback
    after the budget is gone would keep spending and hide the stop."""


class Tracker:
    def __init__(self, limit_usd: float):
        self.limit_usd = limit_usd
        self.spent_usd = 0.0
        self.reached = False


_tracker: contextvars.ContextVar[Tracker | None] = contextvars.ContextVar("fmea_spend_limit", default=None)


@contextmanager
def spend_limit(usd: float):
    tracker = Tracker(usd)
    token = _tracker.set(tracker)
    try:
        yield tracker
    finally:
        _tracker.reset(token)


_lock = threading.Lock()      # the two remediation agents record from separate threads


def check_before_call() -> None:
    tracker = _tracker.get()
    if tracker is not None and tracker.reached:
        raise BudgetReached(f"The spend limit of ${tracker.limit_usd:.2f} was reached.")


def record(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    tracker = _tracker.get()
    if tracker is None:
        return
    with _lock:
        tracker.spent_usd += compute_cost(model, prompt_tokens, completion_tokens)
        over = tracker.spent_usd >= tracker.limit_usd
        if over:
            tracker.reached = True
    if over:
        raise BudgetReached(f"The spend limit of ${tracker.limit_usd:.2f} was reached.")
