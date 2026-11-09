"""
core/line_numbers.py — B-041: show the agents their code with line numbers.

Models were given code without line numbers, so the line numbers they cited as evidence
were estimates (a SQL injection at lines 31-33 was cited as 25-27). The pipeline now sends
numbered text to the agents; the original text is what is cached, fingerprinted and stored
for the chat, so nothing downstream sees the prefixes.
"""

from __future__ import annotations

import re

MARKER = ("[Each code line below starts with its line number and '| '. The prefix is not part of the code; "
          "cite evidence as path:line and quote the code without the prefix.]")

# Same header the GitHub fetcher writes (core.github_fetcher.file_block)
_PATH_HEADER = re.compile(r"^# ── (.+?)(?: ─+)?[ \t]*$")


def _is_header(lines: list[str], i: int) -> bool:
    """A real file header: path-like, and at the start or after a blank line (as the fetcher joins files)."""
    m = _PATH_HEADER.match(lines[i])
    if not m:
        return False
    candidate = m.group(1).strip()
    return " " not in candidate and ("." in candidate or "/" in candidate) and (i == 0 or not lines[i - 1].strip())


def number_lines(code: str) -> str:
    """Prefix every code line with `N| `, restarting at 1 under each file header."""
    lines = code.split("\n")
    out: list[str] = [MARKER, ""]
    segment: list[str] = []

    def flush() -> None:
        trailing = 0                                  # blank lines that only separate files stay unnumbered
        while trailing < len(segment) and not segment[-1 - trailing].strip():
            trailing += 1
        body = segment[:len(segment) - trailing]
        out.extend(f"{n}| {line}" for n, line in enumerate(body, 1))
        out.extend(segment[len(segment) - trailing:])
        segment.clear()

    for i, line in enumerate(lines):
        if _is_header(lines, i):
            flush()
            out.append(line)
        else:
            segment.append(line)
    flush()
    return "\n".join(out)
