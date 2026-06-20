"""
memory/scenario_registry.py — Scenario locking with semantic deduplication.

After the first successful pipeline run for a workspace, failure modes and their
RPN scores are locked in the DB (via memory/db.py).  On subsequent runs:

1. The saboteur is given the locked names and told to reproduce them verbatim.
2. The actuary short-circuits locked scenarios (no LLM call; uses stored scores).
3. Any scenario the LLM renamed despite the constraint is matched by embedding
   cosine similarity (threshold 0.85) and renamed back to its canonical name.

Embeddings use OpenAI text-embedding-3-small (cheap: ~$0.02/1M tokens).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from openai import OpenAI

import memory.db as db

if TYPE_CHECKING:
    from core.models import FailureMode, RiskScore

_EMBED_MODEL = "text-embedding-3-small"
_SIMILARITY_THRESHOLD = 0.85

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


# ── Embedding helpers ──────────────────────────────────────────────────────────

def embed_text(text: str) -> np.ndarray:
    """Return a float32 unit-normalised embedding for text."""
    resp = _get_client().embeddings.create(model=_EMBED_MODEL, input=text[:2000])
    vec = np.array(resp.data[0].embedding, dtype=np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two float32 arrays (assumed pre-normalised)."""
    return float(np.dot(a, b))


def _scenario_text(name: str, attack_chain: list[str]) -> str:
    """Canonical text representation used for embedding."""
    first_step = attack_chain[0] if attack_chain else ""
    return f"{name}: {first_step}"


# ── Public API ─────────────────────────────────────────────────────────────────

def get_locked_scenarios(workspace_id: int) -> list[dict]:
    """
    Return all locked scenario dicts for this workspace with any human
    score adjustments overlaid on top of the original actuary values.
    Each dict: failure_mode, severity, occurrence, detection, rpn, embedding (np.ndarray | None).
    """
    scenarios = db.get_locked_scenarios(workspace_id)
    adjustments = db.get_adjustments(workspace_id)
    if not adjustments:
        return scenarios

    # Most-recent adjustment per failure_mode wins (list is already DESC by created_at)
    latest: dict[str, dict] = {}
    for adj in adjustments:
        if adj["failure_mode"] not in latest:
            latest[adj["failure_mode"]] = adj

    for scenario in scenarios:
        adj = latest.get(scenario["failure_mode"])
        if adj:
            scenario["severity"]   = adj["new_s"]
            scenario["occurrence"] = adj["new_o"]
            scenario["detection"]  = adj["new_d"]
            scenario["rpn"]        = adj["new_rpn"]
    return scenarios


def find_matching_scenario(
    candidate_name: str,
    candidate_chain: list[str],
    locked: list[dict],
) -> dict | None:
    """
    Embed the candidate failure mode and compare against locked scenario embeddings.
    Returns the best-matching locked dict if cosine similarity >= threshold, else None.
    Skips locked rows that have no embedding (first run had no embedding stored).
    """
    if not locked:
        return None

    candidates_with_embedding = [row for row in locked if row.get("embedding") is not None]
    if not candidates_with_embedding:
        return None

    candidate_vec = embed_text(_scenario_text(candidate_name, candidate_chain))

    best_score = -1.0
    best_match: dict | None = None
    for row in candidates_with_embedding:
        score = cosine_similarity(candidate_vec, row["embedding"])
        if score > best_score:
            best_score = score
            best_match = row

    if best_score >= _SIMILARITY_THRESHOLD:
        return best_match
    return None


def register_new_scenarios(
    workspace_id: int,
    fingerprint: str,
    failures: list["FailureMode"],
    risks: list["RiskScore"],
    locked: list[dict],
) -> None:
    """
    For each failure mode NOT already in the locked registry, compute an embedding
    and persist it to the scenarios table.  Locked scenarios are left untouched
    (INSERT OR IGNORE in db.upsert_scenario preserves first-run scores).
    """
    locked_names = {row["failure_mode"] for row in locked}

    for failure, risk in zip(failures, risks):
        # Always call upsert — INSERT OR IGNORE means locked ones won't be overwritten
        try:
            embedding_vec = embed_text(
                _scenario_text(failure.failure_mode, failure.attack_chain)
            )
            embedding_bytes = embedding_vec.tobytes()
        except Exception:
            embedding_bytes = b""

        db.upsert_scenario(
            workspace_id=workspace_id,
            fingerprint=fingerprint,
            failure_mode=failure.failure_mode,
            attack_chain=list(failure.attack_chain),
            severity=risk.severity,
            occurrence=risk.occurrence,
            detection=risk.detection,
            rpn=risk.rpn,
            embedding=embedding_bytes,
        )


def clear_registry(workspace_id: int) -> None:
    """Wipe all locked scenarios for this workspace (user-triggered unlock)."""
    db.delete_scenarios(workspace_id)


def scenario_count(workspace_id: int) -> int:
    """Return the number of locked scenarios for this workspace."""
    return db.scenario_count(workspace_id)
