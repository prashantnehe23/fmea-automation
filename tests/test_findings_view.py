"""
B-048 phase 1 (findings view) — the server side: scans stored before the severity floors still show current bands,
and the JS tests exist and are wired in.

  AC  old stored scans show current bands without migration (from B-034)
  AC  the frontend has an automated test suite that CI and developers can run
"""

import json
from pathlib import Path
from types import SimpleNamespace

import memory.db as db
from core.priority import refresh_bands

ROOT = Path(__file__).resolve().parent.parent


def risk(name, s, o, d, priority, reason=""):
    return {"failure_mode": name, "severity": s, "occurrence": o, "detection": d, "rpn": s * o * d,
            "priority": priority, "priority_reason": reason}


def validation(name, realistic=True, complete=True, confidence=0.9):
    return {"failure_mode": name, "is_realistic": realistic, "attack_chain_complete": complete, "confidence": confidence}


def test_an_old_risk_gets_the_severity_floor_and_a_reason():
    result = {"risks": [risk("Backup deletion", 10, 3, 3, "Medium")], "validations": [validation("Backup deletion", confidence=0.2)]}
    out = refresh_bands(result)
    assert out["risks"][0]["priority"] == "High"
    assert "severity 10 floor" in out["risks"][0]["priority_reason"]


def test_a_confirmed_severity_10_with_weak_detection_becomes_critical():
    result = {"risks": [risk("Takeover", 10, 3, 7, "Medium")], "validations": [validation("Takeover")]}
    assert refresh_bands(result)["risks"][0]["priority"] == "Critical"


def test_a_risk_that_already_has_a_reason_is_left_alone():
    result = {"risks": [risk("X", 10, 3, 3, "Critical", "Critical: chosen by the scan")], "validations": []}
    out = refresh_bands(result)
    assert out["risks"][0]["priority"] == "Critical" and out["risks"][0]["priority_reason"] == "Critical: chosen by the scan"


def test_a_result_without_risks_or_validations_is_returned_as_it_is():
    assert refresh_bands({}) == {}
    assert refresh_bands({"risks": [risk("Y", 5, 5, 5, "Medium")]})["risks"][0]["priority"] == "Medium"


def test_the_stored_scan_a_project_opens_carries_current_bands(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fmea.db")
    wid = db.upsert_workspace(SimpleNamespace(customer="Acme", project="api", function="", business_tier="Tier 1",
                                              user_type="x", business_context="", customer_learning=True))
    conn = db.get_db()
    try:
        po = conn.execute("INSERT INTO portfolios (name, created_at) VALUES ('Acme', '2026-01-01')").lastrowid
        pid = conn.execute("INSERT INTO projects (portfolio_id, name, created_at) VALUES (?, 'api', '2026-01-01')", (po,)).lastrowid
        conn.commit()
    finally:
        conn.close()
    db.save_scan_snapshot(wid, None, "fp", {"risks": [risk("Backup deletion", 10, 2, 2, "Medium")], "validations": []}, {})
    shown = db.get_project_scan(pid)["result"]["risks"][0]
    assert shown["priority"] == "High" and shown["priority_reason"]


def test_the_frontend_has_a_test_suite_wired_into_npm():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["test"] == "vitest run"
    assert {"vitest", "@testing-library/react", "jsdom"} <= set(package["devDependencies"])
    assert list((ROOT / "frontend" / "src" / "__tests__").glob("*.test.*"))


def test_the_decision_for_the_test_stack_is_recorded():
    adr = (ROOT / "docs" / "decisions" / "ADR-031-frontend-test-framework.md").read_text(encoding="utf-8")
    assert "Vitest" in adr and "**Status:** Accepted" in adr


def test_a_risk_with_missing_scores_is_skipped_not_fatal():
    result = {"risks": [{"failure_mode": "Broken"}, {"failure_mode": "Odd", "severity": "x", "occurrence": 1, "detection": 1},
                        risk("Fine", 9, 2, 2, "Medium")]}
    out = refresh_bands(result)
    assert "priority_reason" in out["risks"][2] and not out["risks"][0].get("priority_reason") and not out["risks"][1].get("priority_reason")


def test_every_reader_of_a_stored_scan_sees_current_bands(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fmea.db")
    wid = db.upsert_workspace(SimpleNamespace(customer="Acme", project="api", function="", business_tier="Tier 1",
                                              user_type="x", business_context="", customer_learning=True))
    db.save_scan_snapshot(wid, None, "fp", {"failures": [], "risks": [risk("Backup deletion", 10, 2, 2, "Medium")]}, {})
    latest = db.get_latest_snapshot(wid)["findings"]["risks"][0]            # what chat, the PR check and the SARIF export read
    assert latest["priority"] == "High" and "floor" in latest["priority_reason"]
    from core.sarif import export_sarif
    exported = export_sarif(db.get_latest_snapshot(wid)["findings"])
    assert exported["runs"][0]["results"] == []                              # no failures in this stored scan, still well formed


def test_the_exploit_rule_is_the_one_the_pipeline_uses():
    import core.priority as priority
    result = {"risks": [risk("Takeover", 10, 3, 7, "Medium")], "validations": [validation("Takeover", confidence=priority.CONFIRMED_MIN_CONFIDENCE)]}
    assert refresh_bands(result)["risks"][0]["priority"] == "Critical"
    result = {"risks": [risk("Takeover", 10, 3, 7, "Medium")], "validations": [validation("Takeover", confidence=priority.CONFIRMED_MIN_CONFIDENCE - 0.01)]}
    assert refresh_bands(result)["risks"][0]["priority"] == "High"
