"""
api/sse.py — Server-Sent Events helpers.

Each SSE frame is:
    event: <name>\n
    data: <json>\n
    \n
"""

import json
from typing import Any


def sse_event(data: Any, event: str = "message") -> str:
    """Serialise *data* to a single SSE frame string."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
