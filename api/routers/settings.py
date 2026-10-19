"""
api/routers/settings.py — Model selection and pricing endpoints for B-021.

Endpoints:
  GET  /api/settings/models           — list available models with pricing
  GET  /api/settings/model            — get active model
  PATCH /api/settings/model           — set active model
  GET  /api/settings/pricing/refresh  — trigger LiteLLM pricing refresh
  GET  /api/settings/reasoning        — active reasoning level + levels the model supports (B-023)
  PATCH /api/settings/reasoning       — set reasoning level (B-023)
  GET    /api/settings/providers          — providers + masked key status (B-022)
  PUT    /api/settings/providers/{id}/key — store a provider API key (B-022)
  DELETE /api/settings/providers/{id}/key — remove a stored key (B-022)
"""

from fastapi import APIRouter, HTTPException

from api.schemas import ApiKeyBody, ModelPatch, ReasoningPatch
from core.costs import AVAILABLE_MODELS, FALLBACK_RATES, get_rates, refresh_pricing
from core.providers import (
    PROVIDERS, clear_api_key, get_api_key, mask_key, provider_for_model, set_api_key,
)
from core.reasoning import DEFAULT_LEVEL, LEVELS, TOKEN_MULTIPLIER, resolve_level, supported_levels
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
            "key_set":           bool(get_api_key(m["provider"])),
            "reasoning_levels":  [{"level": lv, "token_multiplier": TOKEN_MULTIPLIER[lv]}
                                  for lv in supported_levels(m["id"])],
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
    provider = provider_for_model(body.model)
    if not get_api_key(provider):
        raise HTTPException(
            status_code=409,
            detail=f"No API key set for {PROVIDERS[provider]['display']}. Add one first.",
        )
    set_setting("active_model", body.model)
    return {"active_model": body.model}


def _reasoning_state() -> dict:
    model = get_setting("active_model")
    chosen = get_setting("reasoning_level") or DEFAULT_LEVEL
    effective = resolve_level(model, chosen)
    return {
        "level":       chosen,
        "effective":   effective,
        "supported":   supported_levels(model),
        "token_multiplier": TOKEN_MULTIPLIER.get(effective, 1.0),
    }


@router.get("/api/settings/reasoning")
async def get_reasoning():
    """Chosen level, the level actually applied to the active model, and its supported levels."""
    return _reasoning_state()


@router.patch("/api/settings/reasoning")
async def set_reasoning(body: ReasoningPatch):
    if body.level not in LEVELS:
        raise HTTPException(status_code=422, detail=f"Unknown level '{body.level}'. Valid: {LEVELS}")
    set_setting("reasoning_level", body.level)
    return _reasoning_state()


@router.get("/api/settings/providers")
async def list_providers():
    """Return providers with masked key status. Raw keys are never returned."""
    stored = get_setting("api_keys") or {}
    return [
        {
            "id":       pid,
            "display":  cfg["display"],
            "key_set":  bool(get_api_key(pid)),
            "key_hint": mask_key(get_api_key(pid)),
            "source":   "settings" if stored.get(pid) else ("env" if get_api_key(pid) else None),
        }
        for pid, cfg in PROVIDERS.items()
    ]


@router.put("/api/settings/providers/{provider_id}/key")
async def put_provider_key(provider_id: str, body: ApiKeyBody):
    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    if not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key must not be empty")
    set_api_key(provider_id, body.api_key)
    return {"id": provider_id, "key_set": True, "key_hint": mask_key(body.api_key.strip())}


@router.delete("/api/settings/providers/{provider_id}/key")
async def delete_provider_key(provider_id: str):
    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    clear_api_key(provider_id)
    return {"id": provider_id, "key_set": bool(get_api_key(provider_id))}


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
