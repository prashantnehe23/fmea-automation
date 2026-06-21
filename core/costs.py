"""
core/costs.py — LLM cost tracking for B-021.

Provides per-model pricing ($/1M tokens) with:
- AVAILABLE_MODELS: list of supported models with display metadata
- FALLBACK_RATES:   hardcoded baseline rates in case live fetch fails
- refresh_pricing(): fetch live rates from LiteLLM's public price JSON
- get_rates(model):  return rates from cache, fall back to FALLBACK_RATES
- compute_cost(model, prompt_tok, completion_tok): return cost in USD
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from datetime import datetime

AVAILABLE_MODELS: list[dict] = [
    {"id": "gpt-5.1",     "display": "GPT-5.1",     "tier": "Standard"},
    {"id": "gpt-4o",      "display": "GPT-4o",       "tier": "Power"},
    {"id": "gpt-4o-mini", "display": "GPT-4o mini",  "tier": "Fast"},
]

# $/1M tokens — used when LiteLLM fetch fails or model not found in its JSON
FALLBACK_RATES: dict[str, dict[str, float]] = {
    "gpt-5.1":     {"prompt": 2.00, "completion": 8.00},
    "gpt-4o":      {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
}

_LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)


def refresh_pricing() -> dict[str, dict[str, float]]:
    """Fetch live pricing from LiteLLM JSON and cache in settings. Returns rates dict."""
    try:
        with urllib.request.urlopen(_LITELLM_URL, timeout=5) as resp:
            data: dict = json.loads(resp.read())
    except Exception:
        return {}

    rates: dict[str, dict[str, float]] = {}
    for m in AVAILABLE_MODELS:
        mid = m["id"]
        entry = data.get(mid)
        if entry and entry.get("input_cost_per_token") is not None:
            rates[mid] = {
                "prompt":     round(entry["input_cost_per_token"]  * 1_000_000, 4),
                "completion": round(entry["output_cost_per_token"] * 1_000_000, 4),
            }
        else:
            rates[mid] = FALLBACK_RATES[mid]

    try:
        from core.settings import set_setting
        set_setting("pricing_cache", rates)
        set_setting("pricing_cached_at", datetime.now().isoformat())
    except Exception:
        pass

    return rates


def get_rates(model: str) -> dict[str, float]:
    """Return {prompt: $/1M, completion: $/1M} from cache or FALLBACK_RATES."""
    try:
        from core.settings import get_setting
        cache: dict = get_setting("pricing_cache") or {}
        if model in cache:
            return cache[model]
    except Exception:
        pass
    return FALLBACK_RATES.get(model, FALLBACK_RATES["gpt-5.1"])


def compute_cost(model: str, prompt_tok: int, completion_tok: int) -> float:
    """Return estimated cost in USD for the given token counts."""
    if prompt_tok == 0 and completion_tok == 0:
        return 0.0
    rates = get_rates(model)
    return round(
        (prompt_tok * rates["prompt"] + completion_tok * rates["completion"]) / 1_000_000,
        6,
    )
