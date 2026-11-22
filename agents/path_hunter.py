"""B-028 phase B (ADR-015, ADR-032): hunt exploit paths that cross components, in one packet of connected files."""

import json
import logging
from typing import Callable

from core.llm import call_llm, parse_json_list_leniently
from core.models import ExploitPath, PathStep

_log = logging.getLogger(__name__)
Ask = Callable[[str, int], str]


def default_ask(prompt: str, max_tokens: int) -> str:
    return call_llm(prompt, max_tokens=max_tokens)


QUESTION = """You are a senior application-security reviewer. Below are the source files of connected parts of one
system, with a short map of how they call each other. Find exploit paths that cross components: an attacker-controlled
input enters at an entry point, passes through several components, and reaches something that matters because a check,
a validation or a trust assumption is missing, wrong, or placed in the wrong component.

Look especially at how the pieces fit together:
- a guard, validator or permission rule defined in one place and applied (or not applied) in another;
- tables or registries that wire routes to checks, and what a lookup returns when nothing matches;
- one component assuming another already validated or authenticated the input;
- defaults, settings or environment values that differ between components;
- a second route, helper or background job that reaches the same data without passing the guard.
- services that are protected only by where they run (localhost, an internal network, a private port) and the
  outbound requests, redirects, webhooks or proxies of other components that could reach them.

Follow requests across files; do not stop at the first function. Report only paths you can support with code quoted from
the files shown. Do not list generic hardening advice (rate limiting, headers, logging) or flaws that stay inside one line
of code with no path.

Find exploit paths and answer with a JSON array only. Each item:
{"title": "short name", "entry_point": "method and route, or the function an attacker reaches",
 "steps": [{"file": "path as shown above", "lines": "first-last", "action": "what happens here, including which check is present or absent",
            "quote": "the exact code, copied from the file"}],
 "broken_check": "the check or trust assumption that fails", "exploit": "how an attacker proceeds, in plain steps",
 "impact": "what the attacker gains and who is harmed"}
If you find no exploit path, answer []."""


def build_hunt_prompt(files: dict[str, str], map_summary: str) -> str:
    blocks = "\n\n".join(f"===== FILE: {path} =====\n{text}" for path, text in files.items())
    return f"{QUESTION}\n\nMap of the system:\n{map_summary}\n\n{blocks}\n"


def _coerce(raw: dict) -> ExploitPath:
    steps = [PathStep(**{k: str(s.get(k, ""))[:1200] for k in ("file", "lines", "action", "quote")})
             for s in (raw.get("steps") if isinstance(raw.get("steps"), list) else []) if isinstance(s, dict)]
    return ExploitPath(title=str(raw.get("title") or "Untitled path")[:160], entry_point=str(raw.get("entry_point") or "")[:200],
                       steps=steps[:12], broken_check=str(raw.get("broken_check") or "")[:600],
                       exploit=str(raw.get("exploit") or "")[:800], impact=str(raw.get("impact") or "")[:600])


def parse_paths(text: str) -> list[ExploitPath]:
    try:
        raw = parse_json_list_leniently(text)
    except ValueError:
        return []
    if isinstance(raw, dict):
        raw = raw.get("paths") or raw.get("exploit_paths") or []
    return [_coerce(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def run_path_hunter(files: dict[str, str], map_summary: str, ask: Ask | None = None) -> list[ExploitPath]:
    """One call for one packet. An unreadable answer is no paths; a provider block or spend limit propagates."""
    answer = (ask or default_ask)(build_hunt_prompt(files, map_summary), 8000)
    paths = parse_paths(answer)
    if not paths and answer.strip() not in ("", "[]"):
        _log.info("path hunt gave no readable paths")
    return paths
