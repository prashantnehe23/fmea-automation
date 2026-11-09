"""
core/secret_scan.py — B-033 (ADR-021): secret values never reach a model, and are reported deterministically.

`redact()` replaces secret values with `[REDACTED:<kind>]` before any file text is sent to a provider,
keeping the names and the shape of the code, and returns what it found. The findings never contain
the values. Detection is by pattern and does not depend on any model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    kind: str           # env-file | env-value | private-key | token | hardcoded-secret
    name: str = ""      # the variable or key name, never the value


_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)
_TOKENS = re.compile(
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
    r"|\bsk_live_[A-Za-z0-9]{16,}\b|\bsk-[A-Za-z0-9]{20,}\b"
    r"|\bAIza[0-9A-Za-z_-]{35}\b")
_SECRET_NAME = r"[A-Za-z0-9_.-]*(?:secret|password|passwd|pwd|api[_-]?key|apikey|token|private[_-]?key|credential|access[_-]?key)[A-Za-z0-9_.-]*"
_ASSIGNMENT = re.compile(rf"""(?P<pre>(?P<name>\b{_SECRET_NAME})["']?\s*[:=]\s*(?P<q>["']))(?P<value>[^\s"']{{6,}})(?P=q)""", re.IGNORECASE)
# Unquoted NAME=value / NAME: value, only in files where assignments are literal (shell, docs, Dockerfile, compose, ini, yaml)
# and only for values that contain a digit, so identifiers like `secret_key = settings_secret` are not touched.
_UNQUOTED = re.compile(rf"""(?P<pre>(?P<name>{_SECRET_NAME})\s*[:=]\s*)(?P<value>(?=[^\s]*\d)[A-Za-z0-9+/_.@:-]{{8,}})(?=\s|$|[;,)])""", re.IGNORECASE)
_LITERAL_EXTS = {".sh", ".bash", ".md", ".rst", ".txt", ".adoc", ".properties", ".ini", ".cfg", ".conf", ".yml", ".yaml", ".toml"}
_PLACEHOLDER = re.compile(r"^(?:\$\{?\w+\}?|<.*>|\{\{.*\}\}|%\(.*\)s|your[_-].*|.*(?:xxx|example|placeholder|changeme|dummy|\*\*\*).*)$", re.IGNORECASE)
_ENV_LINE = re.compile(r"^(?P<pre>\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*)(?P<value>\S.*?)\s*$")


def _literal_assignments(path: str) -> bool:
    p = PurePosixPath(path.replace("\\", "/"))
    name = p.name.lower()
    return p.suffix.lower() in _LITERAL_EXTS or name.startswith(("dockerfile", "docker-compose")) or name == "makefile"


def _is_env_file(path: str) -> bool:
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def redact(path: str, text: str) -> tuple[str, list[SecretFinding]]:
    """Return (text with secret values replaced, findings). Findings carry names and lines, never values.

    Every step except the last keeps the line count, so reported line numbers match the original file."""
    findings: list[SecretFinding] = []
    out = text

    def token(m: re.Match) -> str:
        findings.append(SecretFinding(path, _line_of(out, m.start()), "token"))
        return "[REDACTED:token]"

    out = _TOKENS.sub(token, out)

    def assignment(m: re.Match) -> str:
        value = m.group("value")
        if _PLACEHOLDER.match(value) or value.startswith("[REDACTED"):
            return m.group(0)
        findings.append(SecretFinding(path, _line_of(out, m.start()), "hardcoded-secret", m.group("name")))
        return f"{m.group('pre')}[REDACTED:secret]{m.group('q')}"

    out = _ASSIGNMENT.sub(assignment, out)

    def unquoted(m: re.Match) -> str:
        value = m.group("value")
        if _PLACEHOLDER.match(value) or value.startswith("[REDACTED"):
            return m.group(0)
        findings.append(SecretFinding(path, _line_of(out, m.start()), "hardcoded-secret", m.group("name")))
        return f"{m.group('pre')}[REDACTED:secret]"

    if _literal_assignments(path) and not _is_env_file(path):
        out = _UNQUOTED.sub(unquoted, out)

    if _is_env_file(path):
        lines = out.split("\n")
        env_values = 0
        for i, line in enumerate(lines):
            m = _ENV_LINE.match(line)
            if m and not line.lstrip().startswith("#") and "[REDACTED" not in m.group("value"):
                lines[i] = m.group("pre") + "[REDACTED:env-value]"
                findings.append(SecretFinding(path, i + 1, "env-value", m.group("name")))
                env_values += 1
        if env_values or any(f.kind == "hardcoded-secret" for f in findings):
            findings.append(SecretFinding(path, 1, "env-file"))
        out = "\n".join(lines)

    def key_block(m: re.Match) -> str:
        findings.append(SecretFinding(path, _line_of(out, m.start()), "private-key"))
        return "[REDACTED:private-key]"

    out = _PRIVATE_KEY.sub(key_block, out)
    return out, sorted(findings, key=lambda f: (f.line, f.kind))


def finding_dicts(findings: list[SecretFinding]) -> list[dict]:
    return [{"path": f.path, "line": f.line, "kind": f.kind, "name": f.name} for f in findings]
