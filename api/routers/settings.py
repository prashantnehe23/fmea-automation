"""
api/routers/settings.py — Model selection and pricing endpoints for B-021.

Endpoints:
  GET  /api/settings/models           — list available models with pricing
  GET  /api/settings/model            — get active model
  PATCH /api/settings/model           — set active model
  POST /api/settings/pricing/refresh  — trigger LiteLLM pricing refresh
  GET  /api/settings/reasoning        — active reasoning level + levels the model supports (B-023)
  PATCH /api/settings/reasoning       — set reasoning level (B-023)
  GET    /api/settings/providers          — providers + masked key status (B-022)
  PUT    /api/settings/providers/{id}/key — store a provider API key (B-022)
  DELETE /api/settings/providers/{id}/key — remove a stored key (B-022)
"""

import re

from fastapi import APIRouter, HTTPException, Request

from api.schemas import ApiKeyBody, CustomModelBody, EndpointBody, ModelPatch, ReasoningPatch, RepoCredentialBody
from core.costs import AVAILABLE_MODELS, FALLBACK_RATES, all_models, custom_models, get_rates, rates_known, refresh_pricing
from core import auth, providers, repo_credentials
from core.secrets import decrypt
from core.providers import (
    PROVIDERS, add_custom_model, clear_api_key, get_api_key, get_endpoint, is_configured, key_status, mask_key,
    provider_for_model, remove_custom_model, set_api_key, set_endpoint, set_key_status,
)
from core.reasoning import DEFAULT_LEVEL, LEVELS, TOKEN_MULTIPLIER, resolve_level, supported_levels
from core.settings import get_setting, set_setting

router = APIRouter()

@router.get("/api/settings/models")
async def list_models():
    """Return all available models with current pricing and active flag."""
    active = get_setting("active_model")
    result = []
    for m in all_models():
        rates = get_rates(m["id"])
        result.append({
            **m,
            "prompt_per_1m":     rates["prompt"],
            "completion_per_1m": rates["completion"],
            "is_active":         m["id"] == active,
            "key_set":           is_configured(m["provider"]),      # ready to use: key and endpoint where needed
            "rates_known":       rates_known(m["id"]),
            "reasoning_levels":  [{"level": lv, "token_multiplier": TOKEN_MULTIPLIER[lv]}
                                  for lv in supported_levels(m["id"])],
        })
    return result


@router.get("/api/settings/model")
async def get_model():
    """Return the currently active model ID."""
    return {"active_model": get_setting("active_model")}


@router.patch("/api/settings/model")
async def set_model(body: ModelPatch, request: Request):
    """Set the active model. Rejects unknown model IDs."""
    valid = {m["id"] for m in all_models()}
    if body.model not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown model '{body.model}'. Valid: {sorted(valid)}",
        )
    provider = provider_for_model(body.model)
    if PROVIDERS[provider].get("endpoint_required") and not get_endpoint(provider):
        raise HTTPException(status_code=409, detail=f"No endpoint set for {PROVIDERS[provider]['display']}. Add one first.")
    if not is_configured(provider):
        raise HTTPException(
            status_code=409,
            detail=f"No API key set for {PROVIDERS[provider]['display']}. Add one first.",
        )
    set_setting("active_model", body.model)
    auth.record_event(request.state.user, "model_changed", body.model)
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
async def set_reasoning(body: ReasoningPatch, request: Request):
    if body.level not in LEVELS:
        raise HTTPException(status_code=422, detail=f"Unknown level '{body.level}'. Valid: {LEVELS}")
    set_setting("reasoning_level", body.level)
    auth.record_event(request.state.user, "reasoning_changed", body.level)
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
            "source":   "settings" if (stored.get(pid) and decrypt(stored[pid])) else ("env" if get_api_key(pid) else None),
            "status":   key_status(pid),
            "configured":        is_configured(pid),
            "key_optional":      bool(cfg.get("key_optional")),
            "endpoint":          get_endpoint(pid),
            "endpoint_editable": bool(cfg.get("endpoint_required")),
            "custom_models":     bool(cfg.get("custom_models")),
        }
        for pid, cfg in PROVIDERS.items()
    ]


@router.put("/api/settings/providers/{provider_id}/key")
async def put_provider_key(provider_id: str, body: ApiKeyBody, request: Request):
    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    if not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key must not be empty")
    if PROVIDERS[provider_id].get("endpoint_required") and not get_endpoint(provider_id):
        raise HTTPException(status_code=409, detail=f"Set the endpoint for {PROVIDERS[provider_id]['display']} first.")
    key = body.api_key.strip()
    status = providers.verify_key(provider_id, key)
    if status == "invalid":
        raise HTTPException(
            status_code=422,
            detail=f"{PROVIDERS[provider_id]['display']} rejected this key. Check it and try again.",
        )
    set_api_key(provider_id, key)
    set_key_status(provider_id, status)
    auth.record_event(request.state.user, "provider_key_set", provider_id)
    return {"id": provider_id, "key_set": True, "key_hint": mask_key(key), "status": status}


@router.put("/api/settings/providers/{provider_id}/endpoint")
async def put_provider_endpoint(provider_id: str, body: EndpointBody, request: Request):
    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    try:
        set_endpoint(provider_id, body.endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    auth.record_event(request.state.user, "provider_endpoint_set", provider_id)
    return {"id": provider_id, "endpoint": get_endpoint(provider_id)}


@router.post("/api/settings/models/custom")
async def post_custom_model(body: CustomModelBody, request: Request):
    """Add a model the user names themselves (an Azure deployment, a local model)."""
    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{body.provider}'")
    try:
        add_custom_model(body.provider, body.id, body.display, body.prompt_per_1m, body.completion_per_1m)
    except KeyError:
        raise HTTPException(status_code=409, detail=f"A model named '{body.id.strip()}' already exists.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    auth.record_event(request.state.user, "custom_model_added", body.id.strip())
    return {"id": body.id.strip(), "provider": body.provider}


@router.delete("/api/settings/models/custom/{model_id:path}")
async def delete_custom_model(model_id: str, request: Request):
    if not any(m["id"] == model_id for m in custom_models()):
        raise HTTPException(status_code=404, detail=f"'{model_id}' is not a model you added.")
    remove_custom_model(model_id)
    if get_setting("active_model") == model_id:
        set_setting("active_model", "gpt-5.1")
    auth.record_event(request.state.user, "custom_model_removed", model_id)
    return {"id": model_id}


@router.post("/api/settings/providers/{provider_id}/verify")
async def verify_provider_key(provider_id: str):
    """Re-check the key in use for a provider and record the result (B-048)."""
    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    key = get_api_key(provider_id)
    if key:
        set_key_status(provider_id, providers.verify_key(provider_id, key))
    return {"id": provider_id, "status": key_status(provider_id)}


@router.delete("/api/settings/providers/{provider_id}/key")
async def delete_provider_key(provider_id: str, request: Request):
    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    clear_api_key(provider_id)
    auth.record_event(request.state.user, "provider_key_removed", provider_id)
    return {"id": provider_id, "key_set": bool(get_api_key(provider_id))}


_OWNER = re.compile(r"^(\*|[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))?$")


@router.get("/api/settings/repo-credentials")
async def list_repo_credentials():
    """Owners that have a stored repository token, with a masked hint. Never the token."""
    return repo_credentials.list_credentials()


@router.put("/api/settings/repo-credentials")
async def put_repo_credential(body: RepoCredentialBody, request: Request):
    owner = body.owner.strip()
    if not owner or not _OWNER.match(owner):
        raise HTTPException(status_code=422, detail="Enter the GitHub user or organisation the token belongs to, "
                                                    "or * to use it for every owner (wider: anyone who can scan can then read every private repository it reaches).")
    token = body.token.strip()
    if not repo_credentials.valid_token_shape(token):
        raise HTTPException(status_code=422, detail="That does not look like a GitHub token: it must be 10 to 255 printable "
                                                    "characters without spaces or line breaks.")
    status = repo_credentials.verify_token(token)
    if status == "invalid":
        raise HTTPException(status_code=422, detail="GitHub rejected this token. Check it and try again.")
    key = repo_credentials.set_token(owner, token)
    auth.record_event(request.state.user, "repo_credential_set", f"github {key}")
    return {"provider": "github", "owner": key, "hint": mask_key(token), "status": status}


@router.delete("/api/settings/repo-credentials")
async def delete_repo_credential(request: Request, owner: str = ""):
    removed = repo_credentials.remove(owner)
    if removed:
        auth.record_event(request.state.user, "repo_credential_removed", f"github {repo_credentials.normalise_owner(owner)}")
    return {"removed": removed}


@router.post("/api/settings/pricing/refresh")
async def trigger_pricing_refresh():
    """Re-fetch LiteLLM pricing JSON. Falls back to hardcoded rates if fetch fails."""
    rates = refresh_pricing()
    if not rates:
        rates = {m["id"]: FALLBACK_RATES[m["id"]] for m in AVAILABLE_MODELS if m["id"] in FALLBACK_RATES}
        source = "fallback"
    else:
        source = "live"
    return {"rates": rates, "source": source}
