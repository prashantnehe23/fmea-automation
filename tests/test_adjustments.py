"""
tests/test_adjustments.py — B-001: Expert Score Adjustment

Tests cover:
- save_adjustment / get_adjustments DB round-trip
- Adjusted scores are applied when loading locked scenarios
- Adjustments are workspace-isolated (no cross-contamination)
- Most recent adjustment wins when multiple exist for the same failure_mode
"""

import pytest
from pathlib import Path

import memory.db as db
import memory.scenario_registry as registry


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def in_memory_db(tmp_path, monkeypatch):
    """Redirect all DB operations to an isolated temp database per test."""
    db_path = tmp_path / "test_fmea.db"
    monkeypatch.setattr(db, "_DB_PATH", db_path)
    yield db_path


class _FakeWorkspace:
    function = None
    business_tier = "Tier 1"
    user_type = "external_customers"
    business_context = ""
    customer_learning = True

    def __init__(self, customer="TestCo", project="TestProj"):
        self.customer = customer
        self.project  = project


def _make_workspace(customer="TestCo", project="TestProj") -> int:
    """Insert a minimal workspace and return its id."""
    return db.upsert_workspace(_FakeWorkspace(customer, project))


# ── DB layer tests ────────────────────────────────────────────────────────────

def test_save_and_get_adjustment():
    ws_id = _make_workspace()
    adj_id = db.save_adjustment(
        workspace_id=ws_id,
        failure_mode="SQL Injection via login endpoint",
        new_s=9, new_o=7, new_d=6,
        justification="Penetration test confirmed exploitability; raised occurrence.",
    )
    assert adj_id is not None and adj_id > 0

    rows = db.get_adjustments(ws_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["failure_mode"] == "SQL Injection via login endpoint"
    assert row["new_s"] == 9
    assert row["new_o"] == 7
    assert row["new_d"] == 6
    assert row["new_rpn"] == 9 * 7 * 6  # 378
    assert "Penetration test" in row["justification"]
    assert row["created_at"]


def test_multiple_adjustments_ordered_newest_first():
    ws_id = _make_workspace()
    db.save_adjustment(ws_id, "Race Condition in checkout", 5, 4, 7, "First assessment")
    db.save_adjustment(ws_id, "Race Condition in checkout", 6, 4, 7, "Revised after load test")

    rows = db.get_adjustments(ws_id)
    assert len(rows) == 2
    assert rows[0]["justification"] == "Revised after load test"  # newest first


def test_adjustments_workspace_isolation():
    ws1 = _make_workspace(customer="Alpha", project="Proj1")
    ws2 = _make_workspace(customer="Beta",  project="Proj2")
    db.save_adjustment(ws1, "XSS in dashboard", 7, 5, 6, "Found in review")

    assert len(db.get_adjustments(ws1)) == 1
    assert len(db.get_adjustments(ws2)) == 0


# ── Scenario registry overlay tests ──────────────────────────────────────────

def _insert_locked_scenario(ws_id: int, failure_mode: str, s: int, o: int, d: int):
    """Insert a scenario row directly, bypassing embedding (uses empty bytes)."""
    db.upsert_scenario(
        workspace_id=ws_id,
        fingerprint="test-fp",
        failure_mode=failure_mode,
        attack_chain=["step1", "step2"],
        severity=s,
        occurrence=o,
        detection=d,
        rpn=s * o * d,
        embedding=b"",
    )


def test_get_locked_scenarios_applies_adjustment():
    ws_id = _make_workspace()
    _insert_locked_scenario(ws_id, "Unvalidated Redirect", s=5, o=4, d=6)

    # No adjustment yet — original scores returned
    scenarios = registry.get_locked_scenarios(ws_id)
    assert len(scenarios) == 1
    assert scenarios[0]["severity"]   == 5
    assert scenarios[0]["occurrence"] == 4
    assert scenarios[0]["detection"]  == 6
    assert scenarios[0]["rpn"]        == 120

    # After adjustment — overridden scores returned
    db.save_adjustment(ws_id, "Unvalidated Redirect", new_s=8, new_o=4, new_d=6,
                       justification="Manual review raised severity")
    scenarios = registry.get_locked_scenarios(ws_id)
    assert len(scenarios) == 1
    assert scenarios[0]["severity"]   == 8
    assert scenarios[0]["occurrence"] == 4
    assert scenarios[0]["detection"]  == 6
    assert scenarios[0]["rpn"]        == 8 * 4 * 6  # 192


def test_most_recent_adjustment_wins():
    ws_id = _make_workspace()
    _insert_locked_scenario(ws_id, "Secrets in env vars", s=7, o=5, d=8)
    db.save_adjustment(ws_id, "Secrets in env vars", 7, 5, 8, "Initial")
    db.save_adjustment(ws_id, "Secrets in env vars", 9, 6, 8, "Revised upward")

    scenarios = registry.get_locked_scenarios(ws_id)
    assert scenarios[0]["severity"]   == 9
    assert scenarios[0]["occurrence"] == 6


def test_adjustment_does_not_affect_other_workspace_scenarios():
    ws1 = _make_workspace(customer="Co1", project="P1")
    ws2 = _make_workspace(customer="Co2", project="P2")
    _insert_locked_scenario(ws1, "Missing rate limit", s=6, o=7, d=5)
    _insert_locked_scenario(ws2, "Missing rate limit", s=6, o=7, d=5)
    db.save_adjustment(ws1, "Missing rate limit", 8, 7, 5, "Confirmed by pen test")

    ws2_scenarios = registry.get_locked_scenarios(ws2)
    assert ws2_scenarios[0]["severity"] == 6  # unchanged


def test_unadjusted_scenarios_retain_original_scores():
    ws_id = _make_workspace()
    _insert_locked_scenario(ws_id, "Path Traversal", s=7, o=3, d=6)
    _insert_locked_scenario(ws_id, "SSRF via webhook", s=8, o=4, d=7)
    db.save_adjustment(ws_id, "Path Traversal", 9, 3, 6, "Revised severity")

    scenarios = {s["failure_mode"]: s for s in registry.get_locked_scenarios(ws_id)}
    assert scenarios["Path Traversal"]["severity"] == 9   # adjusted
    assert scenarios["SSRF via webhook"]["severity"] == 8  # untouched
