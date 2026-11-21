"""
B-044 — repository hygiene and an honest README.

Each test maps to an acceptance criterion in docs/BACKLOG.md (B-044).
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _tracked() -> list[str]:
    try:
        return _git("ls-files").splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")


def test_only_python_sources_tracked_under_memory():
    offenders = [f for f in _tracked() if f.startswith("memory/") and not f.endswith(".py")]
    assert offenders == []


@pytest.mark.parametrize("path", [
    "memory/fmea.db",
    "memory/fmea.db-wal",
    "memory/fmea.db-shm",
    "memory/analysis_cache.json",
    "memory/learning_memory.json",
    "memory/workspaces/acme/checkout/learning_memory.json",
    "memory/core/eval_history.json",
])
def test_runtime_data_is_gitignored(path):
    try:
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    except OSError:
        pytest.skip("git not available")
    assert result.returncode == 0, f"{path} is not ignored"


def test_fresh_checkout_starts_api_and_creates_empty_database(tmp_path):
    """Copy only what git tracks (what a clone contains), start the API, and read the empty DB."""
    for rel in _tracked():
        if rel.split("/")[0] not in {"api", "agents", "core", "memory", "workflows"}:
            continue
        src = ROOT / rel
        if not src.is_file():
            continue
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    assert not (tmp_path / "memory" / "fmea.db").exists()
    script = (
        "from fastapi.testclient import TestClient\n"
        "from api.main import app\n"
        "c = TestClient(app)\n"
        "r = c.get('/api/health')\n"
        "assert r.status_code == 200 and r.json()['database'] == 'ok', r.text\n"
        "r = c.get('/api/auth/status')\n"
        "assert r.status_code == 200 and r.json()['setup_required'] is True, r.text\n"   # empty database: first-run setup
        "assert c.get('/api/portfolios').status_code == 401\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "memory" / "fmea.db").exists()


def test_no_compliance_alignment_claims_in_readme_or_landing():
    claim = re.compile(r"GDPR|PCI[- ]?DSS|SOC ?2|ISO ?27001|Annex A|HIPAA", re.IGNORECASE)
    files = [ROOT / "README.md", *sorted((ROOT / "landing").rglob("*.html"))]
    hits = [
        f"{f.relative_to(ROOT)}:{n}: {line.strip()}"
        for f in files if f.exists()
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if claim.search(line)
    ]
    assert hits == []


def test_readme_links_resolve():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\((?!https?:|#|mailto:)([^)\s#]+)", text)
    missing = [t for t in targets if not (ROOT / t).exists()]
    assert missing == []


def test_readme_names_every_registered_provider():
    from core.providers import PROVIDERS

    text = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [p["display"] for p in PROVIDERS.values() if p["display"] not in text]
    assert missing == []


def test_readme_has_no_stale_claims():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for stale in ("(planned)", "mock data", "ADR-001 – ADR-008", "OPENAI_API_KEY=sk-"):
        assert stale not in text, stale


def test_duplicate_skilss_file_removed():
    assert not (ROOT / "SKILSS.md").exists()
