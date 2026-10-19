"""
OpenAI-compatible LLM wrapper (OpenAI, Mistral, …) used by all agents.

Exports:
    call_llm(prompt, *, max_tokens)  → raw response string from the model
    extract_json_text(text)          → JSON substring stripped of markdown fences / preamble
    reset_call_count()               → reset the per-run call counter to zero
    get_call_count()                 → return calls made since last reset
"""

from __future__ import annotations

import os
import re

import openai

_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.1")
_clients: dict[str, tuple[str, openai.OpenAI]] = {}


def _get_model() -> str:
    """Return the active model from settings, falling back to _MODEL."""
    try:
        from core.settings import get_setting
        return get_setting("active_model") or _MODEL
    except Exception:
        return _MODEL


def get_model_name() -> str:
    """Return the currently configured model ID."""
    return _get_model()
_call_count: int = 0
_prompt_tokens: int = 0
_completion_tokens: int = 0


def _get_client(provider_id: str) -> openai.OpenAI:
    """Return a client for the provider using its current key (rebuilt if the key changes)."""
    from core.providers import get_api_key, get_provider
    api_key = get_api_key(provider_id)
    if not api_key:
        cfg = get_provider(provider_id)
        raise RuntimeError(
            f"No API key for {cfg['display']}. Enter one in Settings or set {cfg['env_var']}."
        )
    cached = _clients.get(provider_id)
    if cached is None or cached[0] != api_key:
        cfg = get_provider(provider_id)
        cached = (api_key, openai.OpenAI(api_key=api_key, base_url=cfg["base_url"]))
        _clients[provider_id] = cached
    return cached[1]


def reset_call_count() -> None:
    """Reset the per-run LLM call counter and token accumulators."""
    global _call_count, _prompt_tokens, _completion_tokens
    _call_count = 0
    _prompt_tokens = 0
    _completion_tokens = 0


def get_call_count() -> int:
    """Return the number of LLM calls made since the last reset."""
    return _call_count


def get_token_usage() -> tuple[int, int]:
    """Return (prompt_tokens, completion_tokens) accumulated since last reset."""
    return _prompt_tokens, _completion_tokens


def _content_text(content) -> str:
    """Normalise message content to text. Some providers (Mistral) return a list of
    chunks (text, thinking, ...) instead of a string; keep only the text chunks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for chunk in content:
        if isinstance(chunk, str):
            parts.append(chunk)
        else:
            get = chunk.get if isinstance(chunk, dict) else lambda k, d=None: getattr(chunk, k, d)
            if get("type", "text") == "text":
                parts.append(get("text", "") or "")
    return "".join(parts)


def call_llm(prompt: str, *, max_tokens: int = 4096) -> str:
    """Send a single-turn prompt to the configured model and return the text reply.

    Model-agnostic safeguards: the user's reasoning level (core/reasoning.py) sets the
    model's reasoning param and scales max_tokens, since reasoning tokens count against it.
    A reply cut off by the token limit (finish_reason "length") is retried once with a
    larger budget before failing with a clear error instead of returning broken JSON.
    """
    global _call_count, _prompt_tokens, _completion_tokens
    from core.providers import get_provider, provider_for_model
    from core.reasoning import DEFAULT_LEVEL, request_params
    from core.settings import get_setting
    model = _get_model()
    provider_id = provider_for_model(model)
    client = _get_client(provider_id)
    token_param = get_provider(provider_id)["max_tokens_param"]
    params, multiplier, cap = request_params(model, get_setting("reasoning_level") or DEFAULT_LEVEL)
    budget = min(int(max_tokens * multiplier), cap)

    for attempt in range(2):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            **{token_param: budget},
            **params,
        )
        _call_count += 1
        if response.usage:
            _prompt_tokens     += response.usage.prompt_tokens or 0
            _completion_tokens += response.usage.completion_tokens or 0
        choice = response.choices[0]
        if choice.finish_reason != "length":
            return _content_text(choice.message.content)
        if attempt == 0:
            budget = min(budget * 2, cap)
    raise RuntimeError(
        f"{model} reply was cut off at {budget} tokens. The model may be spending its "
        "budget on reasoning; lower the reasoning level in Settings or choose another model."
    )


def _repair_json(text: str) -> str:
    """
    State-machine JSON repair for LLM output quirks.

    Handles (correctly distinguishing inside-string vs outside-string context):
      - Trailing commas before } or ]
      - // line comments and /* */ block comments
      - Ellipsis ... used as placeholder values  → null
      - Python-style True / False / None         → true / false / null
      - Unescaped newlines / tabs inside strings → escaped \\n / \\t
    """
    out: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        c = text[i]

        # ── String literal — collect with escape-awareness ────────────────────
        if c == '"':
            out.append(c)
            i += 1
            while i < n:
                sc = text[i]
                if sc == '\\' and i + 1 < n:          # valid escape — pass through
                    out.append(sc)
                    out.append(text[i + 1])
                    i += 2
                elif sc == '"':                         # closing quote
                    out.append(sc)
                    i += 1
                    break
                elif sc == '\n':                        # bare newline inside string
                    out.append('\\n')
                    i += 1
                elif sc == '\r':
                    out.append('\\r')
                    i += 1
                elif sc == '\t':
                    out.append('\\t')
                    i += 1
                else:
                    out.append(sc)
                    i += 1

        # ── // line comment ───────────────────────────────────────────────────
        elif c == '/' and i + 1 < n and text[i + 1] == '/':
            while i < n and text[i] != '\n':
                i += 1                                  # skip; preserve newline below

        # ── /* */ block comment ───────────────────────────────────────────────
        elif c == '/' and i + 1 < n and text[i + 1] == '*':
            i += 2
            while i < n - 1 and not (text[i] == '*' and text[i + 1] == '/'):
                i += 1
            i += 2                                      # skip closing */

        # ── Ellipsis placeholder → null ───────────────────────────────────────
        elif text[i:i + 3] == '...':
            out.append('null')
            i += 3

        # ── Python True / False / None → JSON equivalents ────────────────────
        elif text[i:i + 4] == 'True' and (i + 4 >= n or not text[i + 4].isalnum()):
            out.append('true');  i += 4
        elif text[i:i + 5] == 'False' and (i + 5 >= n or not text[i + 5].isalnum()):
            out.append('false'); i += 5
        elif text[i:i + 4] == 'None' and (i + 4 >= n or not text[i + 4].isalnum()):
            out.append('null');  i += 4

        else:
            out.append(c)
            i += 1

    # Trailing-comma removal is safe now that strings are clean and comments gone
    cleaned = ''.join(out)

    # Add missing commas between consecutive JSON values.
    # At this point bare newlines only appear between tokens (not inside strings),
    # so we can safely regex-match token boundaries.
    # Value-end chars: closing quote, digit, e(true/false), l(null), }, ]
    # Value-start chars: opening quote, {, [, digit, t/f/n (true/false/null)
    # Run BEFORE trailing-comma removal so any spurious trailing comma gets cleaned up.
    cleaned = re.sub(
        r'(["\d}\]el])(\s*\n)(\s*["{\[\dtfn])',
        r'\1,\2\3',
        cleaned,
    )

    cleaned = re.sub(r',(\s*[}\]])', r'\1', cleaned)
    return cleaned


def extract_json_text(text: str) -> str:
    """
    Extract and repair a JSON object or array from an LLM response.

    Handles:
      - ```json ... ``` fences
      - ``` ... ``` fences (no language tag)
      - Bare JSON with explanatory prose before/after
      - Trailing commas, // comments, /* */ comments, ellipsis (newer models)
    """
    # Strip markdown code fences (```json or ```)
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        return _repair_json(fenced.group(1).strip())

    # Find the first { or [ and the matching last } or ]
    first_brace = text.find("{")
    first_bracket = text.find("[")

    if first_brace == -1 and first_bracket == -1:
        return text.strip()

    if first_brace == -1:
        start = first_bracket
        close = "]"
    elif first_bracket == -1:
        start = first_brace
        close = "}"
    else:
        start = min(first_brace, first_bracket)
        close = "}" if start == first_brace else "]"

    end = text.rfind(close)
    if end == -1:
        return _repair_json(text[start:].strip())

    return _repair_json(text[start : end + 1].strip())
