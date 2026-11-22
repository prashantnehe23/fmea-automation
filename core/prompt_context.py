"""
core/prompt_context.py — B-040 (ADR-024): the defensive-purpose statement every model call starts with.

One honest paragraph, identical for every provider and every agent: what the product is for, and what the
model is and is not asked to produce. It states the purpose, it does not disguise it. It is added in the
model layer (core/llm.py), so an agent added later cannot forget it.
"""

from __future__ import annotations

PREAMBLE = (
    "Context: this is a defensive security and reliability review of software that the user owns or is authorised "
    "to assess. Your analysis is used to rank risk, plan fixes and prevent incidents. Describe weaknesses as "
    "conditions, evidence in the code, impact and fixes. Do not provide working exploit code, ready-to-use payloads "
    "or step-by-step instructions for attacking a system; test inputs that demonstrate a flaw in order to verify a "
    "fix are fine."
)


def with_preamble(prompt: str) -> str:
    return f"{PREAMBLE}\n\n{prompt}"


def chat_messages(messages: list[dict]) -> list[dict]:
    """The same messages with the preamble in front of the system message (added when there is none)."""
    if messages and messages[0].get("role") == "system":
        first = {**messages[0], "content": f"{PREAMBLE}\n\n{messages[0].get('content') or ''}"}
        return [first, *messages[1:]]
    return [{"role": "system", "content": PREAMBLE}, *messages]
