"""
core/repo_credentials.py — B-043 (ADR-027 point 9): access tokens for private GitHub repositories.

A fine-grained personal access token is scoped to one GitHub owner (a user or an organisation), so
credentials are stored per owner. The owner "*" is a catch-all for classic tokens that span owners.
Tokens are encrypted at rest with FMEA_SECRET_KEY (core/secrets.py), are never returned by the API
after saving, and are only ever sent to api.github.com as a bearer token. The fetcher looks the
token up itself, so nothing that reaches a model, a log or the telemetry table carries it.
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.request

from core.providers import mask_key
from core.secrets import decrypt, encrypt
from core.settings import get_setting, set_setting

SETTING = "repo_credentials"
_lock = threading.Lock()
_TOKEN = re.compile(r"^[\x21-\x7e]{10,255}$")        # printable ASCII, no spaces or newlines


def valid_token_shape(token: str) -> bool:
    return bool(_TOKEN.match(token))


def normalise_owner(owner: str | None) -> str:
    cleaned = (owner or "").strip().lower()
    return "*" if cleaned in ("", "*") else cleaned


def _github() -> dict:
    return dict((get_setting(SETTING) or {}).get("github") or {})


def set_token(owner: str | None, token: str) -> str:
    key = normalise_owner(owner)
    with _lock:
        store = _github()
        store[key] = encrypt(token.strip())
        set_setting(SETTING, {"github": store})
    return key


def remove(owner: str | None) -> bool:
    key = normalise_owner(owner)
    with _lock:
        store = _github()
        if key not in store:
            return False
        del store[key]
        set_setting(SETTING, {"github": store})
    return True


def token_for(owner: str | None) -> str | None:
    """The token for a GitHub owner: the owner's own, else the catch-all, else None."""
    store = _github()
    for key in (normalise_owner(owner), "*"):
        value = store.get(key)
        token = decrypt(value) if value else None
        if token:
            return token
    return None


def list_credentials() -> list[dict]:
    """Owners with a stored token and a masked hint. Never the token itself."""
    return [
        {"provider": "github", "owner": owner, "hint": mask_key(decrypt(value))}
        for owner, value in sorted(_github().items())
    ]


def verify_token(token: str) -> str:
    """Ask GitHub whether the token is accepted: "valid", "invalid" (401) or "unverified" (could not tell)."""
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "fmea-automation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return "valid"
    except urllib.error.HTTPError as exc:
        return "invalid" if exc.code == 401 else "unverified"
    except Exception:
        return "unverified"
