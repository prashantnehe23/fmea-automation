"""
core/llm_errors.py — B-048 phase 0: turn a failure during a scan into a plain message for the user.

The raw provider text (for example "Error code: 401 - {'detail': ...}") is logged on the server and
never sent to the browser. `action: "open_settings"` tells the UI to offer a button to the key setting.
"""

from __future__ import annotations

import logging

import openai

from core.llm import MissingApiKeyError, get_model_name
from core.providers import PROVIDERS, provider_for_model, set_key_status

log = logging.getLogger(__name__)


def scan_error_event(exc: Exception) -> dict:
    """Return the SSE error payload {"stage": "error", "msg", "code", "action"} for *exc*."""
    log.warning("scan failed: %s: %s", type(exc).__name__, exc)
    provider_id = provider_for_model(get_model_name())
    name = PROVIDERS[provider_id]["display"]

    code, action, msg = "scan_failed", None, "The scan failed. The details are in the API server log."
    if isinstance(exc, MissingApiKeyError):
        code, action = "key_missing", "open_settings"
        msg = f"No {name} API key is set. Add one in Settings."
    elif isinstance(exc, openai.AuthenticationError):
        set_key_status(provider_id, "invalid")
        code, action = "key_invalid", "open_settings"
        msg = f"Your {name} API key was rejected. It may have expired or been revoked. Add a new key in Settings."
    elif isinstance(exc, openai.PermissionDeniedError):
        code, action = "key_forbidden", "open_settings"
        msg = (f"Your {name} API key does not have access to this model. "
               "Check the key's permissions or choose another model in Settings.")
    elif isinstance(exc, openai.RateLimitError):
        code = "rate_limited"
        msg = f"{name} is limiting requests, or your quota is used up. Wait a minute and try again, or check your plan with {name}."
    elif isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        code = "provider_unreachable"
        msg = f"Could not reach {name}. Check your network connection and try again."
    return {"stage": "error", "msg": msg, "code": code, "action": action}
