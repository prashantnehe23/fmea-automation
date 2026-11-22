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
    # B-047 (ADR-030): OpenAI-protocol providers. None has an embedding model here: scenario matching
    # then relies on exact names and finding identity (B-031).
    "anthropic": {
        "display":          "Anthropic",
        "base_url":         "https://api.anthropic.com/v1/",    # Anthropic's OpenAI-compatibility endpoint
        "env_var":          "ANTHROPIC_API_KEY",
        "max_tokens_param": "max_tokens",
        "embed_model":      None,
        "omit_temperature": True,    # newer Claude models reject temperature below 1
    },
    "azure": {
        "display":          "Azure OpenAI",
        "base_url":         None,     # the user's resource: https://<resource>.openai.azure.com/openai/v1/
        "endpoint_required": True,
        "endpoint_env":     "AZURE_OPENAI_ENDPOINT",
        "env_var":          "AZURE_OPENAI_API_KEY",
        "max_tokens_param": "max_completion_tokens",
        "embed_model":      None,
        "custom_models":    True,     # the model name is the user's deployment name
    },
    "local": {
        "display":          "Local endpoint",
        "base_url":         None,     # any OpenAI-compatible server: Ollama, vLLM, LM Studio, a company gateway
        "endpoint_required": True,
        "endpoint_env":     "LOCAL_LLM_BASE_URL",
        "key_optional":     True,
        "env_var":          "LOCAL_LLM_API_KEY",
        "max_tokens_param": "max_tokens",
        "embed_model":      None,
        "custom_models":    True,
    },
    # Google Gemini through its OpenAI-compatible endpoint, which Google documents as beta (checked 2026-11-22). The
    # token-parameter name and temperature handling are not stated there; max_tokens is the common one. The model name
    # is the user's (for example the id shown in Google AI Studio), so there is no built-in list or price.
    "gemini": {
        "display":          "Google Gemini",
        "base_url":         "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_var":          "GEMINI_API_KEY",
        "max_tokens_param": "max_tokens",
        "embed_model":      "gemini-embedding-001",
        "custom_models":    True,
    },
}

DEFAULT_PROVIDER = "openai"


def get_provider(provider_id: str) -> dict:
    if provider_id not in PROVIDERS:
        raise KeyError(f"Unknown provider '{provider_id}'. Valid: {sorted(PROVIDERS)}")
    return PROVIDERS[provider_id]


def provider_for_model(model_id: str) -> str:
    from core.costs import all_models
    for m in all_models():
        if m["id"] == model_id:
            return m["provider"]
    return DEFAULT_PROVIDER


def model_supports_tools(model_id: str) -> bool:
    """Whether the model supports tool calling (registry field "tool_calling", default True)."""
    from core.costs import all_models
    for m in all_models():
        if m["id"] == model_id:
            return m.get("tool_calling", True)
    return True


def get_endpoint(provider_id: str) -> str | None:
    """The base URL requests go to: the user's setting, else the environment, else the provider's own."""
    cfg = get_provider(provider_id)
    if not cfg.get("endpoint_required"):
        return cfg["base_url"]
    stored = (get_setting("provider_endpoints") or {}).get(provider_id)
    if stored:
        return stored
    try:                                                   # an environment value gets the same checks as a typed one
        return validate_endpoint(provider_id, os.environ.get(cfg["endpoint_env"], "")) or None
    except ValueError:
        return None


def validate_endpoint(provider_id: str, url: str) -> str:
    """The cleaned URL, or ValueError. Keys must not travel in the clear, except to a local endpoint."""
    from urllib.parse import urlsplit
    cfg = get_provider(provider_id)
    if not cfg.get("endpoint_required"):
        raise ValueError(f"{cfg['display']} has a fixed endpoint.")
    import ipaddress
    url = (url or "").strip()
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or port == -1):
        raise ValueError("Enter a full http(s) URL without a user name, password or query.")
    if parts.scheme == "http" and provider_id != "local":
        raise ValueError(f"{cfg['display']} needs an https URL.")
    host = parts.hostname.lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if host == "metadata.google.internal" or (ip and (ip.is_link_local or ip.is_multicast or ip.is_unspecified)):
        raise ValueError("That address is not allowed (link-local and metadata addresses are refused).")
    if ip and provider_id != "local" and (ip.is_private or ip.is_loopback):
        raise ValueError(f"{cfg['display']} is a hosted service: use its host name, not a private address.")
    return url


def set_endpoint(provider_id: str, url: str) -> None:
    url = validate_endpoint(provider_id, url)
    endpoints = dict(get_setting("provider_endpoints") or {})
    if endpoints.get(provider_id) not in (None, url):
        clear_api_key(provider_id)                     # a stored key is never carried over to a different host
    endpoints[provider_id] = url
    set_setting("provider_endpoints", endpoints)


def is_configured(provider_id: str) -> bool:
    """Ready to take a request: an endpoint where one is needed, and a key unless the provider needs none."""
    cfg = get_provider(provider_id)
    if cfg.get("endpoint_required") and not get_endpoint(provider_id):
        return False
    return bool(get_api_key(provider_id)) or bool(cfg.get("key_optional"))


def add_custom_model(provider_id: str, model_id: str, display: str, prompt_per_1m: float | None = None,
                     completion_per_1m: float | None = None) -> None:
    from core.costs import AVAILABLE_MODELS, custom_models
    if not get_provider(provider_id).get("custom_models"):
        raise ValueError(f"{get_provider(provider_id)['display']} has a fixed list of models.")
    model_id = model_id.strip()
    if not model_id:
        raise ValueError("A model name is required.")
    if any(m["id"] == model_id for m in AVAILABLE_MODELS) or any(m["id"] == model_id for m in custom_models()):
        raise KeyError(model_id)
    if len(model_id) > 120 or any(ord(c) < 32 for c in model_id):
        raise ValueError("A model name is at most 120 characters, without control characters.")
    if (prompt_per_1m is None) != (completion_per_1m is None):
        raise ValueError("Give both prices or neither.")
    entry = {"id": model_id, "provider": provider_id, "display": (display or model_id).strip()[:120], "tier": "Custom"}
    if prompt_per_1m is not None:
        import math
        if not all(math.isfinite(v) and v >= 0 for v in (prompt_per_1m, completion_per_1m)):
            raise ValueError("Prices must be zero or more.")
        entry.update(prompt_per_1m=prompt_per_1m, completion_per_1m=completion_per_1m)
    set_setting("custom_models", custom_models() + [entry])


def remove_custom_model(model_id: str) -> None:
    from core.costs import custom_models
    set_setting("custom_models", [m for m in custom_models() if m["id"] != model_id])


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
    endpoint = get_endpoint(provider_id)
    if cfg.get("endpoint_required") and not endpoint:
        return "unverified"                            # never send a key to the SDK's default host
    try:
        client = openai.OpenAI(api_key=key, base_url=endpoint, timeout=10, max_retries=0)
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
        return "unchecked" if get_provider(provider_id).get("key_optional") else "missing"
    rec = (get_setting("key_status") or {}).get(provider_id)
    if not rec or rec.get("key_id") != _key_id(key):
        return "unchecked"
    return rec["status"]
