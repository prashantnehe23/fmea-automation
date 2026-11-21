"""
core/retention.py — B-042 (ADR-026): how long scanned source code is kept.

FMEA_SOURCE_RETENTION_DAYS (environment) wins over the `source_retention_days` setting; the default is
30. 0 means scanned source is not kept at all. Findings are kept either way.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from core.settings import get_setting

log = logging.getLogger(__name__)

DEFAULT_DAYS = 30


def _as_days(value) -> int | None:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days >= 0 else None


def purge_now() -> int:
    """Delete stored source older than the retention period. Returns files deleted."""
    import memory.db as db
    return db.purge_expired_sources(retention_days())


def start_background_purge(interval_seconds: int = 6 * 3600) -> threading.Thread:
    """Purge every few hours so a long-running install enforces retention without new scans."""
    def loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                purge_now()
            except Exception:
                log.warning("scheduled source purge failed", exc_info=True)

    thread = threading.Thread(target=loop, daemon=True, name="fmea-source-purge")
    thread.start()
    return thread


def retention_days() -> int:
    from_env = _as_days(os.environ.get("FMEA_SOURCE_RETENTION_DAYS"))
    if from_env is not None:
        return from_env
    from_setting = _as_days(get_setting("source_retention_days"))
    return from_setting if from_setting is not None else DEFAULT_DAYS
