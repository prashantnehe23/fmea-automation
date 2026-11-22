"""
Learning memory: the system gets smarter with every FMEA run.

Stores historical failure patterns, known attack chains, and an aggression level
that grows over time so the saboteur becomes increasingly thorough.

The learning context is injected into the saboteur prompt each run, so new code
is tested against accumulated knowledge from all prior analyses.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.paths import data_dir
from core.root_cause import category_for
from typing import Any

LEARNING_PATH = data_dir(Path(__file__).parent) / "learning_memory.json"

# Aggression levels and their descriptions injected into the saboteur prompt
_AGGRESSION_DESCRIPTIONS = {
    1: "Be thorough and systematic. Cover all standard OWASP categories.",
    2: "Be thorough. Probe for non-obvious chained weaknesses across boundaries.",
    3: (
        "Be rigorous. Challenge every assumption about trust and input validation. "
        "Look for combinations of weaknesses that together lead to a larger impact."
    ),
    4: (
        "Be highly rigorous. Consider how an informed user with bad intent could misuse the system. "
        "Examine race conditions, state corruption, and privilege escalation paths."
    ),
    5: (
        "Be exhaustive. Look for edge cases others miss. "
        "Consider how low-severity weaknesses combine into severe impacts. "
        "Treat no assumption as safe."
    ),
}


# ── Internal helpers ────────────────────────────────────────────────────────────

def _empty_memory() -> dict[str, Any]:
    return {
        "version": 1,
        "aggression_level": 1,
        "total_analyses": 0,
        "patterns": [],          # List[PatternEntry]
        "global_attack_chains": [],  # Cross-analysis attack chain snippets
    }


# ── I/O ─────────────────────────────────────────────────────────────────────────

def load_learning_memory() -> dict[str, Any]:
    if LEARNING_PATH.exists():
        try:
            data = json.loads(LEARNING_PATH.read_text(encoding="utf-8"))
            # Backfill new keys if opening an older file
            data.setdefault("global_attack_chains", [])
            data.setdefault("version", 1)
            return data
        except Exception:
            return _empty_memory()
    return _empty_memory()


def _save_learning_memory(memory: dict[str, Any]) -> None:
    LEARNING_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARNING_PATH.write_text(
        json.dumps(memory, indent=2, default=str), encoding="utf-8"
    )


# ── Core update logic ────────────────────────────────────────────────────────────

def update_from_run(failures: list, risks: list, domains: dict | None = None) -> None:
    """
    Called after every successful FMEA pipeline run.
    Updates pattern frequencies, extends known attack chains, and raises
    the aggression level as the system accumulates experience.
    """
    memory = load_learning_memory()
    memory["total_analyses"] += 1

    # Aggression grows: level 2 after 2 runs, level 3 after 5, 4 after 10, 5 after 20
    thresholds = [(20, 5), (10, 4), (5, 3), (2, 2), (0, 1)]
    for threshold, level in thresholds:
        if memory["total_analyses"] >= threshold:
            memory["aggression_level"] = level
            break

    patterns_by_key: dict[str, dict] = {
        p["pattern_key"]: p for p in memory["patterns"]
    }

    for failure, risk in zip(failures, risks):
        category = category_for((domains or {}).get(failure.failure_mode))
        key = category  # aggregate by category so patterns accumulate across runs

        # Collect novel attack chain steps (deduplicated)
        new_steps = [
            s for s in failure.attack_chain
            if len(s) > 10  # filter trivial one-word steps
        ]

        if key in patterns_by_key:
            p = patterns_by_key[key]
            p["frequency"] += 1
            p["last_seen"] = datetime.now().isoformat()
            # Rolling average for scores
            n = p["frequency"]
            p["avg_severity"] = round(
                (p["avg_severity"] * (n - 1) + risk.severity) / n, 1
            )
            p["avg_occurrence"] = round(
                (p["avg_occurrence"] * (n - 1) + risk.occurrence) / n, 1
            )
            p["avg_detection"] = round(
                (p["avg_detection"] * (n - 1) + risk.detection) / n, 1
            )
            p["avg_rpn"] = round(p["avg_severity"] * p["avg_occurrence"] * p["avg_detection"], 1)
            # Keep up to 10 example attack chain steps per category
            existing_steps: list[str] = p.get("example_attack_steps", [])
            for step in new_steps:
                if step not in existing_steps:
                    existing_steps.append(step)
            p["example_attack_steps"] = existing_steps[-10:]
            # Keep a sample of failure_mode names seen in this category
            names: list[str] = p.get("seen_failure_modes", [])
            if failure.failure_mode not in names:
                names.append(failure.failure_mode)
            p["seen_failure_modes"] = names[-5:]
        else:
            patterns_by_key[key] = {
                "pattern_key": key,
                "category": category,
                "frequency": 1,
                "avg_severity": float(risk.severity),
                "avg_occurrence": float(risk.occurrence),
                "avg_detection": float(risk.detection),
                "avg_rpn": float(risk.rpn),
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "example_attack_steps": new_steps[:10],
                "seen_failure_modes": [failure.failure_mode],
            }

    memory["patterns"] = list(patterns_by_key.values())

    # Accumulate global attack chain snippets (unique, capped at 50)
    global_chains: list[str] = memory.get("global_attack_chains", [])
    for failure in failures:
        for step in failure.attack_chain:
            if step not in global_chains and len(step) > 15:
                global_chains.append(step)
    memory["global_attack_chains"] = global_chains[-50:]

    _save_learning_memory(memory)


# ── Prompt injection ─────────────────────────────────────────────────────────────

def get_learning_context() -> str:
    """
    Build the learning-context block injected at the top of the saboteur prompt.
    Returns an empty string on first run (no history yet).
    """
    memory = load_learning_memory()
    if memory["total_analyses"] == 0:
        return ""

    aggression = memory["aggression_level"]
    aggression_desc = _AGGRESSION_DESCRIPTIONS.get(aggression, _AGGRESSION_DESCRIPTIONS[1])

    patterns = sorted(memory["patterns"], key=lambda p: -p["frequency"])
    top_patterns = patterns[:6]

    pattern_lines = "\n".join(
        f"  • {p['category'].replace('_', ' ').title()} "
        f"(seen {p['frequency']}x, avg RPN {p['avg_rpn']:.0f}): "
        + (
            p["seen_failure_modes"][0]
            if p.get("seen_failure_modes")
            else "recurring pattern"
        )
        for p in top_patterns
    )

    chain_samples = memory.get("global_attack_chains", [])[-6:]
    chain_lines = "\n".join(f"  • {s}" for s in chain_samples) if chain_samples else "  (none yet)"

    return f"""
=== LEARNING CONTEXT (from {memory['total_analyses']} prior analyses) ===
Aggression level: {aggression}/5 — {aggression_desc}

High-frequency vulnerability categories to probe aggressively:
{pattern_lines if pattern_lines else '  (no patterns yet)'}

Known attack chain patterns to extend and chain with new findings:
{chain_lines}

Instructions:
- FIRST verify whether any of the above categories appear in this code.
- THEN look for NEW, novel failure modes not seen before.
- If aggression >= 3: Chain multiple low-severity issues into a single high-impact exploit.
- If aggression >= 4: Assume all default configurations are misconfigured.
- Do NOT duplicate failure modes that are trivially identical to known patterns;
  instead EXTEND them with code-specific details.
=== END LEARNING CONTEXT ===
""".strip()


def get_memory_stats() -> dict[str, Any]:
    """Summary dict for dashboard display."""
    memory = load_learning_memory()
    patterns = sorted(memory.get("patterns", []), key=lambda p: -p["frequency"])
    return {
        "total_analyses": memory["total_analyses"],
        "aggression_level": memory["aggression_level"],
        "known_categories": len(patterns),
        "top_patterns": patterns[:5],
        "global_chain_count": len(memory.get("global_attack_chains", [])),
    }
