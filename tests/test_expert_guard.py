"""
tests/test_expert_guard.py — B-034 phase 2: expert adjustments may not quietly bury a catastrophic finding (ADR-020)

  AC5  lowering Severity from >= 9 to < 9 needs a justification (Scoring page API) and is flagged in the audit trail
  AC6  the current severity is the latest adjustment if any, else the registry score
  AC7  other adjustments are unaffected and unflagged
"""

from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import memory.db as db
from core.priority import lowers_catastrophic_severity


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "t.db")
    ws = NS(customer="Acme", project="Pay", function="", business_tier="Tier 1", user_type="x",
            business_context="", customer_learning=True)
    assert db.upsert_workspace(ws) == 1


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def lock(name, s, o=5, d=5):
    db.upsert_scenario(1, "fp", name, ["a"], s, o, d, s * o * d, b"")


def post(client, name, s, justification, o=5, d=5):
    return client.post("/api/scoring/adjustment", json={
        "workspace_id": 1, "failure_mode": name, "new_s": s, "new_o": o, "new_d": d,
        "justification": justification})


REASON = "Card data is tokenised before storage, so the impact is limited."


@pytest.mark.parametrize("cur, new, expected", [
    (10, 8, True), (9, 8, True), (9, 1, True), (9, 9, False), (10, 9, False), (8, 5, False), (5, 3, False)])
def test_what_counts_as_lowering_a_catastrophic_severity(cur, new, expected):
    assert lowers_catastrophic_severity(cur, new) is expected


def test_lowering_below_9_without_a_justification_is_rejected(client):
    lock("Card leak", 10)
    for text in ("ok", "  too short  "):
        r = post(client, "Card leak", 8, text)
        assert r.status_code == 422 and "justification" in r.json()["detail"].lower()
    assert db.get_adjustments(1) == []


def test_lowering_below_9_with_a_justification_is_saved_and_flagged(client):
    lock("Card leak", 10)
    r = post(client, "Card leak", 8, REASON)
    assert r.status_code == 201 and r.json()["flagged"] is True
    assert client.get("/api/scoring/adjustments/1").json()[0]["flagged"] is True


def test_adjustments_that_keep_severity_at_9_or_change_other_scores_are_not_flagged(client):
    lock("Card leak", 10)
    assert post(client, "Card leak", 9, "x", o=3).json()["flagged"] is False
    assert post(client, "Card leak", 10, "x", d=8).status_code == 201


def test_non_catastrophic_scenarios_keep_the_old_minimal_rule(client):
    lock("Slow page", 5)
    r = post(client, "Slow page", 3, "x")
    assert r.status_code == 201 and r.json()["flagged"] is False


def test_unknown_scenarios_cannot_be_judged_so_they_are_not_blocked(client):
    r = post(client, "Never registered", 2, "x")
    assert r.status_code == 201 and r.json()["flagged"] is False


def test_current_severity_follows_the_latest_adjustment(client):
    lock("Card leak", 10)
    assert db.get_current_severity(1, "Card leak") == 10
    post(client, "Card leak", 8, REASON)
    assert db.get_current_severity(1, "Card leak") == 8
    # already below 9: lowering further is an ordinary adjustment
    assert post(client, "Card leak", 6, "x").json()["flagged"] is False
    # raising it back to 9 and lowering again is flagged again
    post(client, "Card leak", 9, "x")
    assert post(client, "Card leak", 7, REASON).json()["flagged"] is True


def test_the_flag_is_set_by_the_shared_save_path_so_chat_apply_is_covered():
    lock("Card leak", 9)
    db.save_adjustment(1, "Card leak", 6, 4, 3, REASON, source="chat")
    [row] = db.get_adjustments(1)
    assert row["flagged"] is True and row["source"] == "chat"


def test_old_rows_without_a_flag_read_as_unflagged():
    db.save_adjustment(1, "Whatever", 5, 5, 5, "x")
    conn = db.get_db()
    conn.execute("UPDATE adjustments SET flagged = NULL")
    conn.commit()
    conn.close()
    assert db.get_adjustments(1)[0]["flagged"] is False
