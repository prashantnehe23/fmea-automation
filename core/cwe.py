"""core/cwe.py — B-045 (ADR-028): CWE identifiers, normalised to 'CWE-<n>' or 'unmapped'."""

from __future__ import annotations

import re
from typing import Any, Iterable

UNMAPPED = "unmapped"
_CWE = re.compile(r"(?i)cwe[\s:_/-]*0*(\d{1,5})(?!\d)")


def normalise_cwe(value: Any) -> str:
    """'CWE-089', 'external/cwe/cwe-89', 'CWE-89: SQL Injection' all become 'CWE-89'; anything else 'unmapped'."""
    match = _CWE.search(str(value or ""))
    return f"CWE-{int(match.group(1))}" if match and int(match.group(1)) > 0 else UNMAPPED


def first_cwe(values: Iterable[Any]) -> str:
    for value in values:
        found = normalise_cwe(value)
        if found != UNMAPPED:
            return found
    return UNMAPPED
