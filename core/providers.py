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

import hashlib
import os
from datetime import datetime, timezone

import openai

from core.secrets import decrypt, encrypt
from core.settings import get_setting, set_setting

PROVIDERS: dict[str, dict] = {
    "openai": {
        "display":          "OpenAI",
        "base_url":         None,  # SDK default
        "env_var":          "OPENAI_API_KEY",
        "max_tokens_param": "max_completion_tokens",
        "embed_model":      "text-embedding-3-small",
        "stream_usage":     True,    # ask for token usage in the final stream chunk
    },
    "mistral": {
        "display":          "Mistral AI",
        "base_url":         "https://api.mistral.ai/v1",
        "env_var":          "MISTRAL_API_KEY",
        "max_tokens_param": "max_tokens",
        "embed_model":      "mistral-embed",
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


def model_supports_tools(model_id: str) -> bool:
    """Whether the model supports tool calling (registry field "tool_calling", default True)."""
    from core.costs import AVAILABLE_MODELS
    for m in AVAILABLE_MODELS:
        if m["id"] == model_id:
            return m.get("tool_calling", True)
    return True


def get_api_key(provider_id: str) -> str | None:
    """Return the user-entered key, falling back to the provider's env var."""
    stored = (get_setting("api_keys") or {}).get(provider_id)
    stored = decrypt(stored) if stored else None
    return stored or os.environ.get(get_provider(provider_id)["env_var"]) or None


def set_api_key(provider_id: str, key: str) -> None:
    get_provider(provider_id)
    keys = dict(get_setting("api_keys") or {})
    keys[provider_id] = encrypt(key.strip())
    set_setting("api_keys", keys)


def clear_api_key(provider_id: str) -> None:
    get_provider(provider_id)
    keys = dict(get_setting("api_keys") or {})
    keys.pop(provider_id, None)
    set_setting("api_keys", keys)


def mask_key(key: str | None) -> str | None:
    return None if not key else "••••" + key[-4:]


# ── Key validity (B-048 phase 0) ──────────────────────────────────────────────

def _key_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def verify_key(provider_id: str, key: str) -> str:
    """
    Ask the provider whether the key is accepted (a cheap model-list call).
    "valid" · "invalid" (the provider answered 401) · "unverified" (could not tell: network
    failure, or a restricted key that may not list models — the key is not rejected for that).
    """
    cfg = get_provider(provider_id)
    try:
        client = openai.OpenAI(api_key=key, base_url=cfg["base_url"], timeout=10, max_retries=0)
        client.models.list()
        return "valid"
    except openai.AuthenticationError:
        return "invalid"
    except Exception:
        return "unverified"


def set_key_status(provider_id: str, status: str) -> None:
    """Record the last check of the key currently in use for the provider."""
    key = get_api_key(provider_id)
    if not key:
        return
    record = dict(get_setting("key_status") or {})
    record[provider_id] = {
        "status": status,
        "key_id": _key_id(key),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    set_setting("key_status", record)


def key_status(provider_id: str) -> str:
    """missing (no key) · unchecked (never checked, or the key changed since) · valid · invalid · unverified."""
    key = get_api_key(provider_id)
    if not key:
        return "missing"
    rec = (get_setting("key_status") or {}).get(provider_id)
    if not rec or rec.get("key_id") != _key_id(key):
        return "unchecked"
    return rec["status"]
