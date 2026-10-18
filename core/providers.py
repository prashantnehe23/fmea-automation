"""
core/providers.py — LLM provider registry and API-key resolution for B-022.

To add a provider that speaks the OpenAI chat-completions protocol, add one entry
to PROVIDERS and its models to core/costs.py AVAILABLE_MODELS. No other code changes.

Provides:
  PROVIDERS                    — registry of supported providers
  get_provider(provider_id)    → provider config dict
  provider_for_model(model_id) → provider id owning the model (default "openai")
  get_api_key(provider_id)     → stored key, else env var, else None
  set_api_key / clear_api_key  → persist / remove a user-entered key
  mask_key(key)                → "••••abcd" for display
"""

from __future__ import annotations

import os

from core.settings import get_setting, set_setting

PROVIDERS: dict[str, dict] = {
    "openai": {
        "display":          "OpenAI",
        "base_url":         None,  # SDK default
        "env_var":          "OPENAI_API_KEY",
        "max_tokens_param": "max_completion_tokens",
    },
    "mistral": {
        "display":          "Mistral AI",
        "base_url":         "https://api.mistral.ai/v1",
        "env_var":          "MISTRAL_API_KEY",
        "max_tokens_param": "max_tokens",
    },
}

DEFAULT_PROVIDER = "openai"


def get_provider(provider_id: str) -> dict:
    if provider_id not in PROVIDERS:
        raise KeyError(f"Unknown provider '{provider_id}'. Valid: {sorted(PROVIDERS)}")
    return PROVIDERS[provider_id]


def provider_for_model(model_id: str) -> str:
    from core.costs import AVAILABLE_MODELS
    for m in AVAILABLE_MODELS:
        if m["id"] == model_id:
            return m["provider"]
    return DEFAULT_PROVIDER


def get_api_key(provider_id: str) -> str | None:
    """Return the user-entered key, falling back to the provider's env var."""
    stored = (get_setting("api_keys") or {}).get(provider_id)
    return stored or os.environ.get(get_provider(provider_id)["env_var"]) or None


def set_api_key(provider_id: str, key: str) -> None:
    get_provider(provider_id)
    keys = dict(get_setting("api_keys") or {})
    keys[provider_id] = key.strip()
    set_setting("api_keys", keys)


def clear_api_key(provider_id: str) -> None:
    get_provider(provider_id)
    keys = dict(get_setting("api_keys") or {})
    keys.pop(provider_id, None)
    set_setting("api_keys", keys)


def mask_key(key: str | None) -> str | None:
    return None if not key else "••••" + key[-4:]
