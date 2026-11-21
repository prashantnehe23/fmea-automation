"""
core/batch_merge.py — B-028 phase 0: combine what the agents found in separate batches of a large repository.
"""

from __future__ import annotations

from core.models import FailureMode, ScenarioLinkageReport, SystemContext


def merge_contexts(contexts: list[SystemContext]) -> SystemContext:
    """Union of the system maps of every batch, in order, without repeats."""
    tiering: dict[str, str] = {}
    surfaces: list[str] = []
    domains: list[str] = []
    for ctx in contexts:
        tiering.update({k: v for k, v in ctx.tiering.items() if k not in tiering})
        surfaces += [s for s in ctx.attack_surfaces if s not in surfaces]
        domains += [d for d in ctx.failure_domains if d not in domains]
    return SystemContext(tiering=tiering, attack_surfaces=surfaces, failure_domains=domains)


def merge_failures(per_batch: list[list[FailureMode]]) -> tuple[list[FailureMode], list[int]]:
    """
    One list of findings and, for each, the batch it came from. A finding reported under the same name (ignoring
    case) by two batches is kept once, the first batch winning. Different names are never merged: two weaknesses
    quoting the same line stay two findings (a duplicate is visible, a lost finding is not).
    """
    merged: list[FailureMode] = []
    origin: list[int] = []
    names: set[str] = set()
    for batch, failures in enumerate(per_batch):
        for f in failures:
            key = f.failure_mode.strip().lower()
            if key in names:
                continue
            names.add(key)
            merged.append(f)
            origin.append(batch)
    return merged, origin


def merge_linkage(reports: list[ScenarioLinkageReport]) -> ScenarioLinkageReport:
    explanations, seen, themes = [], set(), []
    for report in reports:
        for e in report.explanations:
            if e.failure_mode not in seen:
                seen.add(e.failure_mode)
                explanations.append(e)
        if report.cross_cutting_themes and report.cross_cutting_themes not in themes:
            themes.append(report.cross_cutting_themes)
    return ScenarioLinkageReport(explanations=explanations, cross_cutting_themes="\n".join(themes))
