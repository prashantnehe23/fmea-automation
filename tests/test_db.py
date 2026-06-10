"""
tests/test_db.py — Unit tests for memory/db.py (SQLite persistence layer).

Run:  python tests/test_db.py
Uses an isolated temp DB file so tests don't pollute memory/fmea.db.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

# Patch the DB path to a temp file before importing
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
_TMP_DB = _tmp.name

import memory.db as db
db._DB_PATH = Path(_TMP_DB)


class FakeWorkspace:
    customer = "TestCorp"
    project = "TestProject"
    function = "billing"
    business_tier = "Tier 1"
    user_type = "external_customers"
    business_context = "Online payment platform"
    customer_learning = True


class TestUpsertWorkspace(unittest.TestCase):
    def test_roundtrip(self):
        ws = FakeWorkspace()
        wid = db.upsert_workspace(ws)
        self.assertIsInstance(wid, int)
        self.assertGreater(wid, 0)

    def test_idempotent(self):
        """Upserting same customer+project twice returns the same id."""
        ws = FakeWorkspace()
        id1 = db.upsert_workspace(ws)
        id2 = db.upsert_workspace(ws)
        self.assertEqual(id1, id2)


class TestScanPersistence(unittest.TestCase):
    def setUp(self):
        self.ws_id = db.upsert_workspace(FakeWorkspace())

    def test_save_and_retrieve(self):
        result = {"fingerprint": "abc123", "risks": []}
        result_json = json.dumps(result)
        db.save_scan(self.ws_id, "abc123", result_json, llm_calls=5, cost_usd=0.01)
        retrieved = db.get_latest_scan(self.ws_id, "abc123")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["fingerprint"], "abc123")

    def test_latest_scan_returns_most_recent(self):
        db.save_scan(self.ws_id, "fp_x", json.dumps({"v": 1}))
        db.save_scan(self.ws_id, "fp_x", json.dumps({"v": 2}))
        retrieved = db.get_latest_scan(self.ws_id, "fp_x")
        self.assertEqual(retrieved["v"], 2)

    def test_get_all_scans(self):
        db.save_scan(self.ws_id, "fp_hist", json.dumps({}))
        rows = db.get_all_scans(self.ws_id)
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)
        self.assertIn("fingerprint", rows[0])

    def test_no_scan_returns_none(self):
        result = db.get_latest_scan(self.ws_id, "nonexistent_fp")
        self.assertIsNone(result)


class TestScenarioPersistence(unittest.TestCase):
    def setUp(self):
        self.ws_id = db.upsert_workspace(FakeWorkspace())
        # Clear scenarios for clean test
        db.delete_scenarios(self.ws_id)

    def test_upsert_and_retrieve(self):
        embedding = np.random.rand(1536).astype(np.float32)
        db.upsert_scenario(
            workspace_id=self.ws_id,
            fingerprint="fp1",
            failure_mode="SQL Injection via login form",
            attack_chain=["Step 1: craft payload", "Step 2: submit form"],
            severity=8, occurrence=7, detection=5, rpn=280,
            embedding=embedding.tobytes(),
        )
        rows = db.get_locked_scenarios(self.ws_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["failure_mode"], "SQL Injection via login form")
        self.assertEqual(rows[0]["rpn"], 280)
        self.assertIsNotNone(rows[0]["embedding"])
        self.assertIsInstance(rows[0]["embedding"], np.ndarray)
        self.assertEqual(rows[0]["embedding"].shape, (1536,))

    def test_insert_or_ignore_preserves_first(self):
        """Second upsert for same name must not overwrite the first (canonical) scores."""
        embedding = np.ones(1536, dtype=np.float32)
        db.upsert_scenario(self.ws_id, "fp1", "Race Condition", [], 9, 8, 7, 504, embedding.tobytes())
        # Try to overwrite with lower scores
        db.upsert_scenario(self.ws_id, "fp2", "Race Condition", [], 1, 1, 1, 1, embedding.tobytes())
        rows = db.get_locked_scenarios(self.ws_id)
        rc_rows = [r for r in rows if r["failure_mode"] == "Race Condition"]
        self.assertEqual(len(rc_rows), 1)
        self.assertEqual(rc_rows[0]["rpn"], 504)  # first-run score preserved

    def test_delete_scenarios_clears_lock(self):
        embedding = np.ones(1536, dtype=np.float32)
        db.upsert_scenario(self.ws_id, "fp1", "Test Scenario", [], 5, 5, 5, 125, embedding.tobytes())
        self.assertGreater(db.scenario_count(self.ws_id), 0)
        db.delete_scenarios(self.ws_id)
        self.assertEqual(db.scenario_count(self.ws_id), 0)


class TestEvalHistory(unittest.TestCase):
    def setUp(self):
        self.ws_id = db.upsert_workspace(FakeWorkspace())

    def test_save_and_retrieve(self):
        scan_id = db.save_scan(self.ws_id, "fp_eval", json.dumps({}))
        eval_dict = {
            "overall_passed": True,
            "overall_score": 0.82,
            "llm_calls": 8,
            "saboteur_score": 0.9,
        }
        db.save_eval(self.ws_id, scan_id, eval_dict)
        history = db.get_eval_history(self.ws_id, n=5)
        self.assertGreater(len(history), 0)
        latest = history[0]
        self.assertAlmostEqual(latest["overall_score"], 0.82, places=2)
        self.assertIn("agent_scores", latest)

    def test_multiple_evals_ordered(self):
        scan_id = db.save_scan(self.ws_id, "fp_multi", json.dumps({}))
        for score in [0.5, 0.7, 0.9]:
            db.save_eval(self.ws_id, scan_id, {"overall_passed": True, "overall_score": score})
        history = db.get_eval_history(self.ws_id, n=3)
        scores = [h["overall_score"] for h in history]
        # Should be descending by timestamp (most recent first)
        self.assertEqual(scores[0], 0.9)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        # Clean up temp DB
        try:
            os.unlink(_TMP_DB)
        except OSError:
            pass
