"""
tests/test_remediator.py — Unit tests for agents/remediator.py.

Run:  python tests/test_remediator.py
Mocks LLM calls; no real API calls made.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Action, FailureMode, RemediationPlan, RiskScore
from agents.remediator import _apply_patch, _extract_func_name, generate_fix


def _make_failure(name: str = "SQL Injection") -> FailureMode:
    return FailureMode(
        failure_mode=name,
        attack_chain=["Attacker submits crafted payload", "Database executes injection"],
        business_impact="Data breach",
        blast_radius="All user records exposed",
        trigger="Unsanitised user input passed to query",
        evidence="cursor.execute(query % user_input)",
    )


def _make_plan(name: str = "SQL Injection") -> RemediationPlan:
    return RemediationPlan(
        failure_mode=name,
        corrective=[Action(id=f"c{i}", title=t, kind="code_fix", target="db.py", verification="a test")
                    for i, t in enumerate(["Use parameterised queries", "Validate input length", "Enable WAF"], 1)],
        preventive=[Action(id="p1", title="Log all DB errors", kind="monitoring")],
    )


def _make_risk(name: str = "SQL Injection", rpn: int = 336) -> RiskScore:
    return RiskScore(
        failure_mode=name, severity=8, occurrence=7, detection=6, rpn=rpn,
        priority="High", justification="test",
        severity_rationale="", occurrence_rationale="", detection_rationale="",
    )


SAMPLE_CODE = '''
def get_user(user_input):
    query = "SELECT * FROM users WHERE id = %s" % user_input
    cursor.execute(query)
    return cursor.fetchone()

def other_func():
    pass
'''

MOCK_LLM_RESPONSE = json.dumps({
    "code_diff": "--- original\n+++ patched\n@@ -1 +1 @@\n-    query = ...\n+    cursor.execute('SELECT ...', (user_input,))",
    "test_code": "def test_no_sql_injection():\n    result = get_user('1 OR 1=1')\n    assert result is None",
    "test_description": "Verifies that parameterised queries prevent SQL injection via crafted user_input.",
    "patched_snippet": "def get_user(user_input):\n    cursor.execute('SELECT * FROM users WHERE id = %s', (user_input,))\n    return cursor.fetchone()\n",
})


class TestExtractFuncName(unittest.TestCase):
    def test_simple_def(self):
        self.assertEqual(_extract_func_name("def my_func(x):\n    pass"), "my_func")

    def test_async_def(self):
        self.assertEqual(_extract_func_name("async def fetch_data():\n    pass"), "fetch_data")

    def test_no_func(self):
        self.assertIsNone(_extract_func_name("x = 1\ny = 2"))


class TestApplyPatch(unittest.TestCase):
    def test_replaces_known_function(self):
        patched = "def get_user(user_input):\n    cursor.execute('SELECT ...', (user_input,))\n    return cursor.fetchone()\n"
        result = _apply_patch(SAMPLE_CODE, patched)
        self.assertIn("cursor.execute('SELECT", result)
        self.assertNotIn('"SELECT * FROM users WHERE id = %s" % user_input', result)

    def test_appends_when_func_not_found(self):
        patched = "def brand_new_func():\n    pass\n"
        result = _apply_patch(SAMPLE_CODE, patched)
        self.assertIn("brand_new_func", result)
        self.assertIn("get_user", result)  # original still present

    def test_no_func_name_appends(self):
        patched = "x = 1\n"
        result = _apply_patch(SAMPLE_CODE, patched)
        self.assertIn("get_user", result)
        self.assertIn("x = 1", result)


class TestGenerateFix(unittest.TestCase):
    def test_returns_required_fields(self):
        failure = _make_failure()
        plan = _make_plan()

        with patch("agents.remediator.call_llm", return_value=MOCK_LLM_RESPONSE):
            result = generate_fix(failure, plan, SAMPLE_CODE)

        self.assertEqual(result.failure_mode, "SQL Injection")
        self.assertGreater(len(result.code_diff), 10)
        self.assertGreater(len(result.test_code), 10)
        self.assertGreater(len(result.test_description), 5)
        self.assertGreater(len(result.patched_snippet), 10)
        self.assertEqual(result.before_rpn, 0)  # caller fills in
        self.assertFalse(result.applied)

    def test_patched_snippet_is_valid_python(self):
        import ast
        failure = _make_failure()
        plan = _make_plan()

        with patch("agents.remediator.call_llm", return_value=MOCK_LLM_RESPONSE):
            result = generate_fix(failure, plan, SAMPLE_CODE)

        # Should not raise
        ast.parse(result.patched_snippet)

    def test_apply_patch_changes_code(self):
        """End-to-end: generate fix → apply patch → original vulnerability string gone."""
        failure = _make_failure()
        plan = _make_plan()

        with patch("agents.remediator.call_llm", return_value=MOCK_LLM_RESPONSE):
            result = generate_fix(failure, plan, SAMPLE_CODE)

        patched_code = _apply_patch(SAMPLE_CODE, result.patched_snippet)
        self.assertNotIn('"SELECT * FROM users WHERE id = %s" % user_input', patched_code)
        self.assertIn("cursor.execute('SELECT", patched_code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
