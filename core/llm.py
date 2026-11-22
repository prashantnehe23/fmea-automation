"""
OpenAI-compatible LLM wrapper (OpenAI, Mistral, …) used by all agents.

Exports:
    call_llm(prompt, *, max_tokens)  → raw response string from the model
    call_chat(messages, *, tools)    → one multi-turn completion with optional tool calls
    stream_chat(messages, *, tools)  → same, as a generator of ("token", text) / ("done", reply)
    extract_json_text(text)          → JSON substring stripped of markdown fences / preamble
    reset_call_count()               → reset the per-run call counter to zero
    get_call_count()                 → return calls made since last reset
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import threading

import openai

from core import budget, prompt_context
from core.provider_block import ProviderBlocked, is_provider_block
from core.telemetry import current_stage

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
# Per-scan usage (B-042, ADR-026): one mutable counter object per scan, held in a ContextVar. A scan runs
# in one executor thread, so scans never mix; work handed on with asyncio.to_thread or contextvars.copy_context()
# keeps adding to the same scan's counters.
class _Usage:
    __slots__ = ("calls", "prompt", "completion", "salvaged")

    def __init__(self) -> None:
        self.calls = self.prompt = self.completion = self.salvaged = 0


_usage_var: contextvars.ContextVar[_Usage | None] = contextvars.ContextVar("fmea_scan_usage", default=None)
_usage_lock = threading.Lock()


def _current_usage() -> _Usage:
    usage = _usage_var.get()
    if usage is None:
        usage = _Usage()
        _usage_var.set(usage)
    return usage


def _add_usage(calls: int = 0, prompt: int = 0, completion: int = 0) -> None:
    usage = _current_usage()
    with _usage_lock:
        usage.calls += calls
        usage.prompt += prompt
        usage.completion += completion
    if prompt or completion:
        budget.record(get_model_name(), prompt, completion)       # raises BudgetReached inside a spend limit (B-012)


_no_temperature: set[str] = set()     # models that refused a temperature this run (newer OpenAI models allow only the default)


def _refuses_temperature(exc: Exception) -> bool:
    return isinstance(exc, openai.BadRequestError) and "temperature" in str(exc).lower() and "unsupported" in str(exc).lower()


def _create(client, provider_id: str, **kw):
    """The provider call. A policy block becomes ProviderBlocked and is never retried (B-040). A model that refuses a
    temperature is called again without one, and not asked again."""
    if kw.get("model") in _no_temperature:
        kw.pop("temperature", None)
    try:
        return client.chat.completions.create(**kw)
    except Exception as exc:
        if "temperature" in kw and _refuses_temperature(exc):
            _no_temperature.add(kw.get("model", ""))
            kw.pop("temperature")
            return _create(client, provider_id, **kw)
        if is_provider_block(exc):
            raise ProviderBlocked(provider_id, kw.get("model", ""), current_stage()) from None
        raise


def _raise_if_blocked(choice, provider_id: str, model: str) -> None:
    """A filtered or refused answer is a block as well, even when the call itself succeeded."""
    if getattr(choice, "finish_reason", None) == "content_filter" or getattr(getattr(choice, "message", None), "refusal", None):
        raise ProviderBlocked(provider_id, model, current_stage())


class MissingApiKeyError(RuntimeError):
    """No API key is configured for the active provider (B-048: shown to the user as a plain message)."""


def _get_client(provider_id: str) -> openai.OpenAI:
    """Return a client for the provider using its current key (rebuilt if the key changes)."""
    from core.providers import get_api_key, get_endpoint, get_provider
    budget.check_before_call()
    cfg = get_provider(provider_id)
    endpoint = get_endpoint(provider_id)
    if cfg.get("endpoint_required") and not endpoint:
        raise MissingApiKeyError(
            f"No endpoint for {cfg['display']}. Enter its URL in Settings or set {cfg['endpoint_env']}."
        )
    api_key = get_api_key(provider_id) or ("not-needed" if cfg.get("key_optional") else None)   # the SDK wants some value
    if not api_key:
        raise MissingApiKeyError(
            f"No API key for {cfg['display']}. Enter one in Settings or set {cfg['env_var']}."
        )
    cached = _clients.get(provider_id)
    if cached is None or cached[0] != (api_key, endpoint):
        cached = ((api_key, endpoint), openai.OpenAI(api_key=api_key, base_url=endpoint))
        _clients[provider_id] = cached
    return cached[1]


def _sampling(provider: dict) -> dict:
    """Sampling parameters for a request. Some providers reject a temperature (registry: omit_temperature)."""
    return {} if provider.get("omit_temperature") else {"temperature": 0.2}


def reset_call_count() -> None:
    """Reset the per-run LLM call counter and token accumulators."""
    _usage_var.set(_Usage())


def get_call_count() -> int:
    """Return the number of LLM calls made since the last reset."""
    return _current_usage().calls


def get_salvage_count() -> int:
    """Model answers this scan could only use in part (a long JSON array that broke half way)."""
    return _current_usage().salvaged


def get_token_usage() -> tuple[int, int]:
    """Return (prompt_tokens, completion_tokens) accumulated since last reset."""
    usage = _current_usage()
    return usage.prompt, usage.completion


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


_log = logging.getLogger(__name__)

# max_tokens is only a ceiling (you pay for tokens generated), so the first attempt starts
# wide instead of at an agent's small expected size. Verbose models (e.g. Mistral Large 4
# writes a long visible analysis before the JSON) then finish in one pass.
FIRST_ATTEMPT_FLOOR = 16384
MAX_CONTINUATIONS = 3
_WANTS_JSON = re.compile(r"\bJSON\b")
_JSON_STARTED = re.compile(r"^\s*(```(?:json)?\s*)?[\[{]")

_CONTINUE_MSG = (
    "Your previous reply was cut off. Continue exactly where you stopped, without repeating "
    "anything and without any preamble or markdown fences."
)
_RECOVER_MSG = (
    "Using the analysis above, now output ONLY the final JSON in exactly the format the "
    "original request specified: no prose, no explanation, no markdown fences."
)


def _parses(text: str) -> bool:
    try:
        json.loads(extract_json_text(text))
        return True
    except Exception:
        return False


def _salvage_json(text: str) -> str | None:
    """Close a truncated JSON document, dropping only the incomplete trailing item.

    Returns a parseable JSON string keeping every completed element, or None if nothing
    usable can be recovered. Partially written trailing values are dropped, not kept.
    """
    s = extract_json_text(text)
    stack: list[str] = []
    cuts: list[tuple[int, str]] = []  # (end index, closers) at each top-level-safe comma
    in_str = esc = False
    for i, c in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack:
                stack.pop()
        elif c == "," and stack:
            cuts.append((i, "".join(reversed(stack))))
    # Cut at the last completed element: never keep a half-written string or number
    # (e.g. 12 from 123), which could silently change the meaning.
    candidates = list(reversed(cuts))
    if not in_str and s.rstrip()[-1:] in "}]":
        candidates.insert(0, (len(s), "".join(reversed(stack))))
    for end, closers in candidates:
        try:
            json.loads(s[:end].rstrip().rstrip(",") + closers)
            return s[:end].rstrip().rstrip(",") + closers
        except Exception:
            continue
    return None


def call_llm(prompt: str, *, max_tokens: int = 4096) -> str:
    """Send a single-turn prompt to the configured model and return the text reply.

    `max_tokens` is the agent's *expected* size, not a hard limit. Model-agnostic handling
    so verbose or reasoning models never lose their work to a token limit:
      1. The user's reasoning level (core/reasoning.py) sets the model's reasoning param and
         scales the budget (reasoning tokens count against it); the first attempt is wide.
      2. A reply cut off mid-JSON is continued from where it stopped, not discarded.
      3. If the prompt wants JSON but the reply is analysis without it, the analysis is sent
         back and the model is asked for just the JSON.
      4. As a last resort a truncated JSON is closed, keeping every completed item.
    """
    from core.providers import get_provider, provider_for_model
    from core.reasoning import DEFAULT_LEVEL, request_params
    from core.settings import get_setting
    prompt = prompt_context.with_preamble(prompt)        # the defensive purpose, stated once for every provider (B-040)
    model = _get_model()
    provider_id = provider_for_model(model)
    provider = get_provider(provider_id)
    client = _get_client(provider_id)
    params, multiplier, cap = request_params(model, get_setting("reasoning_level") or DEFAULT_LEVEL)
    first_budget = min(max(int(max_tokens * multiplier), FIRST_ATTEMPT_FLOOR), cap)

    def complete(messages: list[dict], budget: int) -> tuple[str, str]:
        response = _create(
            client, provider_id,
            model=model,
            messages=messages,
            **_sampling(provider),
            **{provider["max_tokens_param"]: budget},
            **params,
        )
        _add_usage(calls=1)
        if response.usage:
            _add_usage(prompt=response.usage.prompt_tokens or 0, completion=response.usage.completion_tokens or 0)
        choice = response.choices[0]
        _raise_if_blocked(choice, provider_id, model)
        return _content_text(choice.message.content), choice.finish_reason

    wants_json = bool(_WANTS_JSON.search(prompt))
    user = {"role": "user", "content": prompt}
    text, finish = complete([user], first_budget)

    # 2. Continue a reply that was cut off while it was still producing the answer.
    continuations = 0
    while finish == "length" and (not wants_json or _JSON_STARTED.match(text)) \
            and continuations < MAX_CONTINUATIONS:
        continuations += 1
        _log.warning("%s reply hit the token limit; continuing (%d/%d)",
                     model, continuations, MAX_CONTINUATIONS)
        more, finish = complete(
            [user, {"role": "assistant", "content": text}, {"role": "user", "content": _CONTINUE_MSG}],
            cap,
        )
        # A model that restarts instead of resuming begins a fresh answer: use it alone.
        text = more if _JSON_STARTED.match(more) else text + more

    if not wants_json or _parses(text):
        if finish == "length":
            _log.warning("%s reply still truncated after %d continuations", model, continuations)
        return text

    # 3. Analysis without the JSON (or JSON cut off before a continuation): ask for the JSON,
    #    keeping the model's own analysis in context so none of it is wasted.
    if not _JSON_STARTED.match(text):
        _log.warning("%s reply had no parseable JSON; requesting the JSON from its analysis", model)
        recovered, finish = complete(
            [user, {"role": "assistant", "content": text}, {"role": "user", "content": _RECOVER_MSG}],
            cap,
        )
        if _parses(recovered):
            return recovered
        text = recovered or text

    # 4. Keep everything that was completed rather than failing the whole scan. Only for a
    #    genuinely truncated reply: a complete-but-malformed JSON must not be cut down.
    if finish == "length":
        salvaged = _salvage_json(text)
        if salvaged is not None:
            _log.warning("%s JSON was truncated at the output limit; salvaged %d of %d chars",
                         model, len(salvaged), len(text))
            return salvaged
        raise RuntimeError(
            f"{model} reply was cut off at the model's {cap}-token output limit before any "
            "usable JSON was produced. Try a different model or a smaller selection of files."
        )
    return text


def call_chat(messages: list[dict], *, tools: list[dict] | None = None, max_tokens: int = 4096) -> dict:
    """One multi-turn chat completion with optional tool calling (B-025).

    Same model-agnostic handling as call_llm: the active model and reasoning level, a wide
    token budget, chunked/thinking content reduced to text, and a text answer that hits the
    limit is continued rather than discarded.

    Returns {"message": assistant message in OpenAI format (content, tool_calls?),
             "prompt_tokens": int, "completion_tokens": int}.
    """
    from core.providers import get_provider, provider_for_model
    from core.reasoning import DEFAULT_LEVEL, request_params
    from core.settings import get_setting
    messages = prompt_context.chat_messages(messages)    # B-040: the same defensive-purpose statement
    model = _get_model()
    provider_id = provider_for_model(model)
    provider = get_provider(provider_id)
    client = _get_client(provider_id)
    params, multiplier, cap = request_params(model, get_setting("reasoning_level") or DEFAULT_LEVEL)
    budget = min(max(int(max_tokens * multiplier), FIRST_ATTEMPT_FLOOR), cap)
    prompt_total = completion_total = 0

    def complete(msgs: list[dict], limit: int):
        nonlocal prompt_total, completion_total
        extra = {"tools": tools} if tools else {}
        response = _create(
            client, provider_id,
            model=model,
            messages=msgs,
            **_sampling(provider),
            **{provider["max_tokens_param"]: limit},
            **extra,
            **params,
        )
        _add_usage(calls=1)
        if response.usage:
            p, c = response.usage.prompt_tokens or 0, response.usage.completion_tokens or 0
            _add_usage(prompt=p, completion=c)
            prompt_total += p
            completion_total += c
        choice = response.choices[0]
        _raise_if_blocked(choice, provider_id, model)
        return choice

    choice = complete(messages, budget)
    text = _content_text(choice.message.content)
    raw_calls = getattr(choice.message, "tool_calls", None) or []

    continuations = 0
    while choice.finish_reason == "length" and not raw_calls and continuations < MAX_CONTINUATIONS:
        continuations += 1
        _log.warning("%s chat reply hit the token limit; continuing (%d/%d)",
                     model, continuations, MAX_CONTINUATIONS)
        choice = complete(
            messages + [{"role": "assistant", "content": text},
                        {"role": "user", "content": _CONTINUE_MSG}],
            cap,
        )
        more = _content_text(choice.message.content)
        text += more

    message: dict = {"role": "assistant", "content": text}
    if raw_calls:
        message["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
            for tc in raw_calls
        ]
    return {"message": message, "prompt_tokens": prompt_total, "completion_tokens": completion_total}


def stream_chat(messages: list[dict], *, tools: list[dict] | None = None, max_tokens: int = 4096):
    """Streaming variant of call_chat (B-025). A generator that yields ("token", text) for each
    piece of visible answer text, then ("done", reply) with the same dict call_chat returns.

    Thinking chunks are never streamed. A text answer that hits the limit is continued, and
    its continuation keeps streaming. Closing the generator closes the provider stream, so a
    user's Stop ends generation. If the provider reports no usage, tokens are estimated.
    """
    from core.providers import get_provider, provider_for_model
    from core.reasoning import DEFAULT_LEVEL, request_params
    from core.settings import get_setting
    messages = prompt_context.chat_messages(messages)    # B-040: the same defensive-purpose statement
    model = _get_model()
    provider_id = provider_for_model(model)
    provider = get_provider(provider_id)
    client = _get_client(provider_id)
    params, multiplier, cap = request_params(model, get_setting("reasoning_level") or DEFAULT_LEVEL)
    budget = min(max(int(max_tokens * multiplier), FIRST_ATTEMPT_FLOOR), cap)
    usage_totals = {"prompt": 0, "completion": 0}

    def one_stream(msgs: list[dict], limit: int):
        """Yield ("token", text); return (text, tool_calls, finish_reason)."""
        extra: dict = {"tools": tools} if tools else {}
        if provider.get("stream_usage"):
            extra["stream_options"] = {"include_usage": True}
        stream = _create(
            client, provider_id,
            model=model, messages=msgs, stream=True, **_sampling(provider),
            **{provider["max_tokens_param"]: limit}, **extra, **params,
        )
        text, finish, usage, slots, refused = "", None, None, [], False
        try:
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if getattr(delta, "refusal", None):
                    refused = True
                piece = _content_text(delta.content) if delta.content else ""
                if piece:
                    text += piece
                    yield ("token", piece)
                for tc in getattr(delta, "tool_calls", None) or []:
                    index = getattr(tc, "index", None)
                    if index is None:
                        index = len(slots) if tc.id else max(len(slots) - 1, 0)
                    while len(slots) <= index:
                        slots.append({"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slots[index]["id"] = tc.id
                    if tc.function and tc.function.name:
                        slots[index]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slots[index]["arguments"] += tc.function.arguments
                if choice.finish_reason:
                    finish = choice.finish_reason
        except openai.APIError as exc:                  # an error event in the middle of a stream
            if is_provider_block(exc):
                raise ProviderBlocked(provider_id, model, current_stage()) from None
            raise
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()
        _add_usage(calls=1)
        prompt_used = getattr(usage, "prompt_tokens", None) if usage else None
        completion_used = getattr(usage, "completion_tokens", None) if usage else None
        if prompt_used is None:      # provider sent no usage: estimate (~4 chars per token)
            prompt_used = len(json.dumps(msgs, default=str)) // 4
            completion_used = (len(text) + sum(len(c["arguments"]) for c in slots)) // 4
        _add_usage(prompt=prompt_used, completion=completion_used or 0)
        if finish == "content_filter" or refused:      # the call was billed: its usage is recorded before the block is raised
            raise ProviderBlocked(provider_id, model, current_stage())
        usage_totals["prompt"] += prompt_used
        usage_totals["completion"] += completion_used or 0
        return text, [c for c in slots if c["name"]], finish

    text, calls, finish = yield from one_stream(messages, budget)
    continuations = 0
    while finish == "length" and not calls and continuations < MAX_CONTINUATIONS:
        continuations += 1
        _log.warning("%s streamed reply hit the token limit; continuing (%d/%d)",
                     model, continuations, MAX_CONTINUATIONS)
        more, calls, finish = yield from one_stream(
            messages + [{"role": "assistant", "content": text},
                        {"role": "user", "content": _CONTINUE_MSG}],
            cap,
        )
        text += more

    message: dict = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [
            {"id": c["id"] or f"call_{i}", "type": "function",
             "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
            for i, c in enumerate(calls)
        ]
    yield ("done", {"message": message, "prompt_tokens": usage_totals["prompt"],
                    "completion_tokens": usage_totals["completion"]})


def parse_json_list_leniently(response: str):
    """The model's JSON reply, or, when a long array breaks half way (a stray quote, a missing comma), the complete
    objects before the break (items after the break are lost; the scan's `model_replies_cut` counts such replies). Raises ValueError only when nothing can be recovered. A scan must not die on one bad
    character in a 12 KB answer (B-046: this stopped the scan of a large repository twice)."""
    text = extract_json_text(response)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        start = text.find("[")
        if start == -1 or text[:start].strip():          # only a reply that IS an array is salvaged; an object root is not
            raise
        decoder, pos, items = json.JSONDecoder(), start + 1, []
        while True:
            while pos < len(text) and text[pos] in " \t\r\n,":
                pos += 1
            if pos >= len(text) or text[pos] == "]":
                break
            try:
                item, pos = decoder.raw_decode(text, pos)
            except json.JSONDecodeError:
                break
            items.append(item)
        if not items:
            raise error
        import logging
        logging.getLogger(__name__).warning("model JSON was cut at char %s; kept %s complete items", error.pos, len(items))
        with _usage_lock:
            _current_usage().salvaged += 1             # shown in the scan result: items after the break were lost
        return items


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
                if sc == '\\' and i + 1 < n and (text[i + 1] in '"\\/bfnrt'
                                                 or (text[i + 1] == 'u' and re.fullmatch(r"[0-9a-fA-F]{4}", text[i + 2:i + 6]))):
                    out.append(sc)                      # valid escape — pass through
                    out.append(text[i + 1])
                    i += 2
                elif sc == '\\':                        # a lone backslash (regex or a Windows path in quoted code): escape it
                    out.append('\\\\')
                    i += 1
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
