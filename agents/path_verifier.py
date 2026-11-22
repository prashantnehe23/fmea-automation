"""B-028 phase B (ADR-015, ADR-032): check a claimed exploit path against the code before anyone is told about it.

First without a model: every quoted step must exist in the file it names, and its line numbers are corrected from the file.
A path whose quotes are mostly absent is refuted at no cost. Then one call asks whether the path really works, looking for
defences elsewhere in the excerpts.
"""

import json
import re
from typing import Callable

from agents.path_hunter import default_ask
from core.llm import extract_json_text
from core.models import ExploitPath

Ask = Callable[[str, int], str]
CONTEXT_LINES = 15


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def locate(quote: str, text: str) -> tuple[int, int] | None:
    """First and last line (1-based) of `quote` in `text`, ignoring whitespace differences; None when absent."""
    wanted = _collapse(quote)
    if not wanted:
        return None
    lines = [_collapse(l) for l in text.splitlines()]
    for i in range(len(lines)):
        if not lines[i]:
            continue                                   # a quote starts on a line with code, not on a blank one
        acc = ""
        for j in range(i, min(len(lines), i + 60)):
            acc = (acc + " " + lines[j]).strip()
            at = acc.find(wanted)
            if at != -1 and at <= len(lines[i]):
                return i + 1, j + 1
            if len(acc) > len(wanted) + len(lines[i]) + 2:
                break
    return None


def check_evidence(path: ExploitPath, files: dict[str, str]) -> tuple[ExploitPath, int]:
    """The path with line numbers corrected from the files, and the number of steps whose quote could not be found."""
    steps, missing = [], 0
    for step in path.steps:
        found = locate(step.quote, files.get(step.file, "")) if step.file in files else None
        if found is None:
            missing += 1
            steps.append(step)
        else:
            a, b = found
            steps.append(step.model_copy(update={"lines": str(a) if a == b else f"{a}-{b}"}))
    return path.model_copy(update={"steps": steps}), missing


def _excerpts(path: ExploitPath, files: dict[str, str]) -> str:
    spans: dict[str, list[tuple[int, int]]] = {}
    for step in path.steps:
        m = re.match(r"\s*(\d+)(?:\s*-\s*(\d+))?", step.lines or "")
        if step.file in files and m:
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            spans.setdefault(step.file, []).append((max(1, a - CONTEXT_LINES), b + CONTEXT_LINES))
    blocks = []
    for file, ranges in spans.items():
        lines = files[file].splitlines()
        merged: list[list[int]] = []
        for a, b in sorted(ranges):
            if merged and a <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for a, b in merged:
            body = "\n".join(f"{n}| {lines[n - 1]}" for n in range(a, min(b, len(lines)) + 1))
            blocks.append(f"===== {file} lines {a}-{min(b, len(lines))} =====\n{body}")
    return "\n\n".join(blocks)


def _prompt(path: ExploitPath, files: dict[str, str]) -> str:
    steps = "\n".join(f"{i}. {s.file}:{s.lines} - {s.action}" for i, s in enumerate(path.steps, 1))
    return f"""You are checking a claimed attack path against the code. Does this attack path work? Be a sceptic: the claim
was made by another reviewer who may have missed a check.

Claimed path: {path.title}
Entry point: {path.entry_point}
Steps:
{steps}
The check said to fail: {path.broken_check}
How an attacker proceeds: {path.exploit}

Code excerpts (numbered lines):
{_excerpts(path, files)}

Walk the path step by step. For each step, is the quoted behaviour really what the code does? Look for any defence in the
excerpts, or implied by them, that would stop the attacker: a check that runs earlier or later, a wrapper, a default that
denies, input that is validated elsewhere, a precondition an attacker cannot meet. Do not assume code you cannot see.

Answer with one JSON object only: {{"verdict": "confirmed" | "refuted" | "uncertain", "reason": "one or two sentences
naming the step and the line that decides it"}}. Use "uncertain" when the answer depends on code or configuration not shown."""


def verify_path(path: ExploitPath, files: dict[str, str], ask: Ask | None = None) -> ExploitPath:
    fixed, missing = check_evidence(path, files)
    if not fixed.steps:
        return fixed.model_copy(update={"status": "refuted", "verification": "the path names no steps with code"})
    if missing and missing * 2 >= len(fixed.steps):
        return fixed.model_copy(update={"status": "refuted",
                                        "verification": f"quoted code not found in the files ({missing} of {len(fixed.steps)} steps)"})
    answer = (ask or default_ask)(_prompt(fixed, files), 1500)
    try:
        data = json.loads(extract_json_text(answer))
        verdict = str(data.get("verdict", "")).lower() if isinstance(data, dict) else ""
        reason = str(data.get("reason", ""))[:600] if isinstance(data, dict) else ""
    except ValueError:
        verdict, reason = "", "the verifier's answer could not be read"
    status = verdict if verdict in ("confirmed", "refuted", "uncertain") else "uncertain"
    return fixed.model_copy(update={"status": status, "verification": reason or "no reason given"})
