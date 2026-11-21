"""
core/secrets.py — B-042 (ADR-026): provider keys encrypted at rest.

FMEA_SECRET_KEY (a Fernet key: `python -m core.secrets` prints a new one) encrypts every key the
user enters in Settings. Without it keys are stored as plain text, which is only acceptable for
local development; /api/health reports which mode is active. Keys given as environment variables
are never written to disk.
"""

from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)
PREFIX = "enc:v1:"


class SecretKeyError(RuntimeError):
    """FMEA_SECRET_KEY is set but is not a valid Fernet key."""


def cipher() -> Fernet | None:
    key = os.environ.get("FMEA_SECRET_KEY", "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise SecretKeyError("FMEA_SECRET_KEY is not a valid key. Generate one with: python -m core.secrets") from exc


def key_storage() -> str:
    return "encrypted" if os.environ.get("FMEA_SECRET_KEY", "").strip() else "plaintext"


def encrypt(value: str) -> str:
    c = cipher()
    return value if c is None else PREFIX + c.encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    """Plain text for a stored value, or None if it is encrypted and cannot be opened with the current key."""
    if not value.startswith(PREFIX):
        return value
    c = cipher()
    if c is None:
        log.error("A stored key is encrypted but FMEA_SECRET_KEY is not set")
        return None
    try:
        return c.decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        log.error("A stored key could not be decrypted: FMEA_SECRET_KEY has changed")
        return None


def undecryptable_providers() -> list[str]:
    """Providers whose stored key cannot be opened with the current FMEA_SECRET_KEY (changed or missing)."""
    from core.settings import get_setting
    return sorted(pid for pid, k in (get_setting("api_keys") or {}).items() if k and decrypt(k) is None)


def encrypt_stored_keys() -> None:
    """Encrypt keys saved as plain text before a secret key was configured. No-op without a secret key."""
    from core.settings import get_setting, set_setting
    if cipher() is None:
        return
    keys = dict(get_setting("api_keys") or {})
    changed = {pid: encrypt(k) for pid, k in keys.items() if k and not k.startswith(PREFIX)}
    if changed:
        set_setting("api_keys", {**keys, **changed})


if __name__ == "__main__":
    print(Fernet.generate_key().decode())
