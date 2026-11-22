"""
core/component_map.py — B-028 phase B (ADR-015, ADR-032): how the parts of a project connect, and what to read together.

Static analysers look at one file or one flow at a time. Exploitable flaws often sit between components: a handler layer
that assumes a guard layer checks everything, a table that wires routes to validators, a store that trusts a caller. This
module builds, without a model, a map of files (routes, sinks, guard-like files) and the calls between files, and cuts it
into packets: a seed file plus the files it is wired to, within a byte budget, so the hunt reads the pieces that depend on
each other together.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from core.code_index import _EXT, build_index

POLICY_WORDS = ("auth", "permission", "security", "middleware", "validator", "policy", "acl", "guard", "access",
                "session", "login", "token", "csrf", "cors", "rbac")
CODE_SUFFIXES = tuple(_EXT) + (".go", ".rb", ".php", ".rs", ".kt", ".swift", ".scala", ".c", ".cc", ".cpp", ".h")
_OUTBOUND = re.compile(r"\brequests\.(?:get|post|put|delete|patch|head|request)\(|\bhttpx\.|\burlopen\(|\burllib\.request\b|\baiohttp\.ClientSession"
                       r"|\bfetch\(|\baxios[.(]|\bgot\(|\bhttps?\.(?:get|request)\(|\bHttpClient\b|\bRestTemplate\b|\bWebClient\b")
_RUN_CALL = re.compile(r"\.run\(([^)]*)\)|uvicorn\.run\(([^)]*)\)")
_LISTEN_CALL = re.compile(r"\.listen\(\s*(\d{2,5})")
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|specs|node_modules|vendor|dist|build)(/|$)|(^|/)test_[^/]*$|[._]test\.[a-z]+$|\.spec\.[a-z]+$", re.IGNORECASE)


def is_hunted_code(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in CODE_SUFFIXES and not _TEST_PATH.search(path)


def is_policy_path(path: str) -> bool:
    name = path.lower()
    return any(word in name for word in POLICY_WORDS)


@dataclass
class FileInfo:
    size: int
    routes: list[str] = field(default_factory=list)
    sinks: list[str] = field(default_factory=list)
    policy: bool = False
    supported: bool = True
    outbound: bool = False                        # makes outbound HTTP requests
    listens: list[str] = field(default_factory=list)   # 'host:port' (or the port) it listens on


@dataclass
class Packet:
    seed: str
    files: list[str]
    bytes: int
    oversize: bool = False


@dataclass
class ComponentMap:
    files: dict[str, FileInfo]
    edges: Counter                       # (caller_file, callee_file) -> number of calls
    service_edges: dict = field(default_factory=dict)   # (client_file, server_file) -> why: reachable by network position

    def neighbours(self, path: str) -> list[tuple[str, int]]:
        weight: Counter = Counter()
        for (a, b), n in self.edges.items():
            if a == path:
                weight[b] += n
            elif b == path:
                weight[a] += n
        for a, b in self.service_edges:
            if a == path:
                weight[b] += 1
            elif b == path:
                weight[a] += 1
        return sorted(weight.items(), key=lambda item: (-item[1], item[0]))

    def summary(self, max_chars: int = 6000) -> str:
        """A bounded digest for a model: routes, sinks, guard-like files and who calls whom."""
        lines = [f"{len(self.files)} code files."]
        for path, info in sorted(self.files.items(), key=lambda kv: (-len(kv[1].routes), kv[0])):
            tags = []
            if info.routes:
                tags.append(f"{len(info.routes)} routes: " + ", ".join(info.routes[:8]) + (" ..." if len(info.routes) > 8 else ""))
            tags += [f"{kind} sink" for kind in info.sinks]
            if info.policy:
                tags.append("guard-like file")
            if tags:
                lines.append(f"- {path} [" + "; ".join(tags) + "]")
        for (a, b), n in sorted(self.edges.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"{a} -> {b} ({n} call{'s' if n != 1 else ''})")
        for (a, b), why in sorted(self.service_edges.items()):
            lines.append(f"{a} -> {b} (network: {why})")
        return "\n".join(lines)[:max_chars]


def _network_facts(info: FileInfo, text: str) -> None:
    info.outbound = bool(_OUTBOUND.search(text))
    for match in _RUN_CALL.finditer(text):
        args = match.group(1) or match.group(2) or ""
        port = re.search(r"port\s*=\s*(\d{2,5})", args)
        host = re.search(r"host\s*=\s*[\"']([^\"']+)[\"']", args)
        if port:
            info.listens.append(f"{host.group(1)}:{port.group(1)}" if host else port.group(1))
    info.listens += [m.group(1) for m in _LISTEN_CALL.finditer(text)]


def build_component_map(files: dict[str, str]) -> ComponentMap:
    code = {p: t for p, t in files.items() if is_hunted_code(p)}
    index = build_index({p: t for p, t in code.items() if PurePosixPath(p).suffix.lower() in _EXT})
    info = {p: FileInfo(size=len(t.encode("utf-8", "replace")), policy=is_policy_path(p),
                        supported=PurePosixPath(p).suffix.lower() in _EXT) for p, t in sorted(code.items())}
    for entry in index.entry_points:
        if entry.file in info and entry.route:
            info[entry.file].routes.append(entry.route)
    for sink in index.sinks:
        if sink.file in info and sink.kind not in info[sink.file].sinks:
            info[sink.file].sinks.append(sink.kind)
    for path, text in code.items():
        _network_facts(info[path], text)
    edges: Counter = Counter()
    for call in index.edges():
        if call.callee_file and call.callee_file != call.caller_file and call.callee_file in info and call.caller_file in info:
            edges[(call.caller_file, call.callee_file)] += 1
    service_edges = {}
    for client, ci in info.items():
        if not ci.outbound:
            continue
        for server, si in info.items():
            if server != client and si.routes:
                where = f" and listens on {', '.join(si.listens)}" if si.listens else ""
                service_edges[(client, server)] = f"{client} makes outbound HTTP requests; {server} serves {len(si.routes)} routes{where}"
    return ComponentMap(files=info, edges=edges, service_edges=service_edges)


def make_packets(cmap: ComponentMap, files: dict[str, str], budget_bytes: int = 300_000) -> tuple[list[Packet], list[str]]:
    """Packets to hunt in, and the code files no packet contains (listed, never silently dropped)."""
    def rank(path: str):
        i = cmap.files[path]
        return (-len(i.routes), -len(i.sinks), not i.policy, path)

    seeds = [p for p, i in cmap.files.items() if i.routes or i.sinks or i.policy]
    if not seeds:                  # a library: no routes, sinks or guard-like names, so every code file is read, in packets
        seeds = list(cmap.files)
    packets: list[Packet] = []
    for seed in sorted(seeds, key=rank):
        used = cmap.files[seed].size
        members = [seed]
        if used <= budget_bytes:
            wired = [p for p, _ in cmap.neighbours(seed)]
            guards = sorted(p for p, i in cmap.files.items() if i.policy)
            for path in wired + [g for g in guards if g not in wired]:
                if path not in members and used + cmap.files[path].size <= budget_bytes:
                    members.append(path)
                    used += cmap.files[path].size
        packet = Packet(seed=seed, files=members, bytes=used, oversize=cmap.files[seed].size > budget_bytes)
        if not any(set(members) <= set(earlier.files) for earlier in packets):
            packets.append(packet)
    covered = {p for packet in packets for p in packet.files}
    uncovered = sorted(p for p in files if is_hunted_code(p) and p not in covered)
    return packets, uncovered
