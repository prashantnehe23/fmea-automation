"""
core/path_discovery.py — B-028 phase B (ADR-015, ADR-032): the exploit-path workflow.

Map the components, cut the map into packets of connected files, hunt exploit paths in each packet with a focused question,
verify every path against the code, and hand the verified ones to the normal pipeline as findings (scoring, root cause,
actions and the audit trail then work as they do for any finding). Files no packet contained are reported, not hidden.
"""

from __future__ import annotations

import contextvars
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from agents.path_hunter import Ask, run_path_hunter
from agents.path_verifier import verify_path
from core.component_map import build_component_map, make_packets
from core.models import ExploitPath, FailureMode

WORKERS = 3


@dataclass
class PathDiscovery:
    paths: list[ExploitPath] = field(default_factory=list)
    packet_files: list[list[str]] = field(default_factory=list)
    packet_of: dict[str, int] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)

    def confirmed(self) -> list[ExploitPath]:
        return [p for p in self.paths if p.status == "confirmed"]

    def reportable(self) -> list[ExploitPath]:
        """Confirmed and uncertain paths. A refuted path is never a finding."""
        return [p for p in self.paths if p.status in ("confirmed", "uncertain")]

    @property
    def counts(self) -> dict:
        n = lambda status: sum(1 for p in self.paths if p.status == status)
        return {"packets": len(self.packet_files), "found": len(self.paths), "confirmed": n("confirmed"),
                "refuted": n("refuted"), "uncertain": n("uncertain")}


def _key(path: ExploitPath) -> str:
    return re.sub(r"\W+", " ", f"{path.title} {path.entry_point}".lower()).strip()


def _parallel(function, items: list) -> list:
    """Run in a few threads, each with a copy of this context so usage, spend limits and stages still count.
    A provider block or spend limit raised in a worker reaches the caller."""
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(contextvars.copy_context().run, function, item) for item in items]
        return [f.result() for f in futures]


def discover_exploit_paths(files: dict[str, str], ask: Ask | None = None, budget_bytes: int = 300_000) -> PathDiscovery:
    cmap = build_component_map(files)
    packets, uncovered = make_packets(cmap, files, budget_bytes)
    summary = cmap.summary()
    hunted = _parallel(lambda packet: run_path_hunter({p: files[p] for p in packet.files}, summary, ask), packets)

    unique: list[ExploitPath] = []
    packet_of: dict[str, int] = {}
    seen: set[str] = set()
    for index, found in enumerate(hunted):
        for path in found:
            if _key(path) not in seen:
                seen.add(_key(path))
                unique.append(path)
                packet_of[path.title] = index
    verified = _parallel(lambda path: verify_path(path, files, ask), unique)
    return PathDiscovery(paths=verified, packet_files=[p.files for p in packets], packet_of=packet_of, uncovered=uncovered)


def paths_to_failures(paths: list[ExploitPath]) -> list[FailureMode]:
    """Paths as findings, so the existing stages can score and act on them."""
    out = []
    for path in paths:
        located = next((s for s in path.steps if s.file and s.lines), None)
        evidence = (f"{located.file}:{located.lines}" + (f" `{located.quote[:300]}`" if located.quote else "")) if located else None
        chain = [f"{path.entry_point or 'Entry point'}: attacker-controlled input arrives"] + [
            f"{s.file}:{s.lines} - {s.action}" if s.file else s.action for s in path.steps]
        if path.broken_check:
            chain.append(f"Fails here: {path.broken_check}")
        files = list(dict.fromkeys(s.file for s in path.steps if s.file))
        out.append(FailureMode(
            failure_mode=path.title, attack_chain=chain, business_impact=path.impact or "Not specified",
            blast_radius=("Components on the path: " + ", ".join(files)) if files else "Not specified",
            trigger=path.exploit or "Not specified", evidence=evidence, exploit_path=path.steps,
            path_status=path.status if path.status in ("confirmed", "uncertain") else ""))
    return out
