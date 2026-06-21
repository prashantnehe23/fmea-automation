"""
tests/test_costs.py — B-021: Cost per run tracking

Tests cover acceptance criteria:
  AC1: compute_cost() returns correct USD for known token counts
  AC2: Unknown model falls back gracefully (no crash)
  AC3: Zero tokens produce zero cost
  AC4: cost_usd is persisted and returned in telemetry DB round-trip
"""

import pytest
import memory.db as db
from core.costs import compute_cost, FALLBACK_RATES


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def in_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_costs.db"
    monkeypatch.setattr(db, "_DB_PATH", db_path)
    yield db_path


# ── AC1: compute_cost() is accurate for known token counts ───────────────────

def test_compute_cost_gpt5_known_tokens():
    # 1000 prompt + 500 completion on gpt-5.1 ($2/1M prompt, $8/1M completion)
    expected = round((1000 * 2.00 + 500 * 8.00) / 1_000_000, 6)
    assert compute_cost("gpt-5.1", 1000, 500) == expected


def test_compute_cost_gpt4o_mini():
    # 10000 prompt + 2000 completion on gpt-4o-mini ($0.15/1M, $0.60/1M)
    expected = round((10000 * 0.15 + 2000 * 0.60) / 1_000_000, 6)
    assert compute_cost("gpt-4o-mini", 10000, 2000) == expected


# ── AC2: Unknown model falls back without raising ────────────────────────────

def test_compute_cost_unknown_model_does_not_raise():
    cost = compute_cost("gpt-99-turbo-ultra", 500, 500)
    assert isinstance(cost, float)
    assert cost >= 0


# ── AC3: Zero tokens yield zero cost ─────────────────────────────────────────

def test_compute_cost_zero_tokens():
    assert compute_cost("gpt-5.1", 0, 0) == 0.0
    assert compute_cost("gpt-4o", 0, 0) == 0.0


# ── AC4: cost_usd round-trips through the telemetry DB ───────────────────────

def test_cost_usd_persisted_in_telemetry():
    import uuid
    run_id = str(uuid.uuid4())
    cost = compute_cost("gpt-5.1", 1000, 200)

    db.save_telemetry_span(
        run_id=run_id,
        scan_id=None,
        workspace_id=1,
        agent="saboteur",
        duration_ms=1234.5,
        prompt_tokens=1000,
        completion_tokens=200,
        cost_usd=cost,
    )

    summary = db.get_telemetry_summary(workspace_id=1, n_scans=5)
    assert summary["cost_summary"]["last_scan_usd"] == pytest.approx(cost, rel=1e-5)
    assert "saboteur" in summary["cost_summary"]["per_agent_usd"]
