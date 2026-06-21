"""
api/routers/settings.py — Model selection and pricing endpoints for B-021.

Endpoints:
  GET  /api/settings/models           — list available models with pricing
  GET  /api/settings/model            — get active model
  PATCH /api/settings/model           — set active model
  GET  /api/settings/pricing/refresh  — trigger LiteLLM pricing refresh
"""

from fastapi import APIRouter, HTTPException

from api.schemas import ModelPatch
from core.costs import AVAILABLE_MODELS, FALLBACK_RATES, get_rates, refresh_pricing
from core.settings import get_setting, set_setting

router = APIRouter()

_VALID_IDS = {m["id"] for m in AVAILABLE_MODELS}


@router.get("/api/settings/models")
async def list_models():
    """Return all available models with current pricing and active flag."""
    active = get_setting("active_model")
    result = []
    for m in AVAILABLE_MODELS:
        rates = get_rates(m["id"])
        result.append({
            **m,
            "prompt_per_1m":     rates["prompt"],
            "completion_per_1m": rates["completion"],
            "is_active":         m["id"] == active,
        })
    return result


@router.get("/api/settings/model")
async def get_model():
    """Return the currently active model ID."""
    return {"active_model": get_setting("active_model")}


@router.patch("/api/settings/model")
async def set_model(body: ModelPatch):
    """Set the active model. Rejects unknown model IDs."""
    if body.model not in _VALID_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown model '{body.model}'. Valid: {sorted(_VALID_IDS)}",
        )
    set_setting("active_model", body.model)
    return {"active_model": body.model}


@router.get("/api/settings/pricing/refresh")
async def trigger_pricing_refresh():
    """Re-fetch LiteLLM pricing JSON. Falls back to hardcoded rates if fetch fails."""
    rates = refresh_pricing()
    if not rates:
        rates = {m["id"]: FALLBACK_RATES[m["id"]] for m in AVAILABLE_MODELS}
        source = "fallback"
    else:
        source = "live"
    return {"rates": rates, "source": source}
