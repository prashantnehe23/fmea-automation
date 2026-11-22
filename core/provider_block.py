"""
core/provider_block.py — B-040 (ADR-024): a model provider refused a request on policy grounds.

A block is its own, visible outcome. It is classified from the provider's answer (Mistral's guardrail 403,
OpenAI's content filter and refusals), never retried with the same prompt, and shown to the user with the
provider, the model and the stage so that they can choose another model. Nothing switches model silently.

ProviderBlocked is a BaseException on purpose: agents catch Exception to fall back when a call fails, and a
fallback after a block would hide it and ask the provider again.
"""

from __future__ import annotations

import openai


class ProviderBlocked(BaseException):
    def __init__(self, provider: str, model: str, stage: str = ""):
        super().__init__(f"{provider} blocked the request ({model}, {stage or 'unknown stage'})")
        self.provider, self.model, self.stage = provider, model, stage


_FILTER_WORDS = ("content_filter", "content_policy_violation", "guardrail_violation", "invalid_prompt", "usage policy")


def is_provider_block(exc: BaseException) -> bool:
    """A policy block from the provider, as opposed to a bad key, a rate limit, a size limit or an outage.

    Also covers an error that arrives mid-stream (an APIError with no HTTP status of its own)."""
    if not isinstance(exc, openai.APIError):
        return False
    body = exc.body if isinstance(getattr(exc, "body", None), dict) else {}
    inner = body.get("error") if isinstance(body.get("error"), dict) else {}
    text = " ".join(str(v).lower() for v in (body.get("type"), body.get("code"), body.get("message"),
                                              inner.get("type"), inner.get("code"), inner.get("message"),
                                              getattr(exc, "code", None), getattr(exc, "message", None)))
    status = getattr(exc, "status_code", None)
    if status is not None and status not in (400, 403):
        return False                                      # a quoted filter word in a 5xx is not a policy block
    if any(word in text for word in _FILTER_WORDS):
        return True
    return status == 403 and ("guardrail" in text or "1920" in text)


def blocked_message(exc: ProviderBlocked, what: str = "scan") -> str:
    """Plain words for the user: who blocked it, where, and what to do."""
    from core.providers import PROVIDERS
    name = PROVIDERS.get(exc.provider, {}).get("display", exc.provider)
    where = f"during the {exc.stage} stage" if exc.stage else "while handling your request"
    again = "ask again" if what == "chat" else "run it again" if what == "scan" else "try again"
    return (f"{name} ({exc.model}) blocked the request {where}: its safety policy refused the prompt. "
            f"Choose another model in Settings and {again}.")
