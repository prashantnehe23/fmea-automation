"""
core/settings.py — JSON-backed settings store for B-021.

File: core/settings.json (auto-created on first write).

Provides:
  get_setting(key)        → Any
  set_setting(key, value) → None
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
_lock = threading.Lock()

_DEFAULTS: dict[str, Any] = {
    "active_model":      "gpt-5.1",
    "pricing_cache":     {},
    "pricing_cached_at": None,
}


def _load() -> dict[str, Any]:
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_setting(key: str) -> Any:
    """Return setting value, falling back to default if absent."""
    with _lock:
        return _load().get(key, _DEFAULTS.get(key))


def set_setting(key: str, value: Any) -> None:
    """Persist a single setting value. Creates settings.json if absent."""
    with _lock:
        data = _load()
        data[key] = value
        _save(data)
