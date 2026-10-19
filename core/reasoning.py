"""
core/reasoning.py — user-selectable reasoning level for B-023.

A model opts in via a "reasoning" entry in core/costs.py AVAILABLE_MODELS:

    "reasoning": {"param": "reasoning_effort", "levels": {"off": "none", "high": "high"}}

`levels` maps the generic level names (LEVELS) to the provider's API value, so each model
exposes only what it supports. Models without the entry have no control (hidden in the UI).

Reasoning tokens count against the output-token limit, so a higher level also scales each
agent's max_tokens (TOKEN_MULTIPLIER), capped at the model's "max_output_tokens".

Provides:
  LEVELS, TOKEN_MULTIPLIER, DEFAULT_LEVEL
  supported_levels(model_id)       → list of generic levels the model offers ([] if none)
  resolve_level(model_id, level)   → highest supported level <= level (else lowest supported)
  request_params(model_id, level)  → ({api param: value}, token multiplier, max token cap)
"""

from __future__ import annotations

LEVELS = ["off", "low", "medium", "high"]
TOKEN_MULTIPLIER = {"off": 1.0, "low": 1.5, "medium": 2.5, "high": 4.0}
DEFAULT_LEVEL = "off"
DEFAULT_MAX_OUTPUT_TOKENS = 32768


def _model(model_id: str) -> dict:
    from core.costs import AVAILABLE_MODELS
    return next((m for m in AVAILABLE_MODELS if m["id"] == model_id), {})


def supported_levels(model_id: str) -> list[str]:
    levels = (_model(model_id).get("reasoning") or {}).get("levels", {})
    return [lv for lv in LEVELS if lv in levels]


def resolve_level(model_id: str, level: str) -> str | None:
    """Map the user's chosen level onto one the model supports (None if no control)."""
    supported = supported_levels(model_id)
    if not supported:
        return None
    wanted = LEVELS.index(level) if level in LEVELS else 0
    at_or_below = [lv for lv in supported if LEVELS.index(lv) <= wanted]
    return at_or_below[-1] if at_or_below else supported[0]


def request_params(model_id: str, level: str) -> tuple[dict, float, int]:
    """Return (extra request params, token multiplier, max token cap) for this model + level."""
    model = _model(model_id)
    cap = model.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
    resolved = resolve_level(model_id, level)
    if resolved is None:
        return {}, 1.0, cap
    cfg = model["reasoning"]
    return {cfg["param"]: cfg["levels"][resolved]}, TOKEN_MULTIPLIER[resolved], cap
