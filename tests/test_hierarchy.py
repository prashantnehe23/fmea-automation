"""
tests/test_hierarchy.py — B-007: Full Hierarchy Persistence in SQLite

Tests cover acceptance criteria:
  AC1: Creating a portfolio/project writes to SQLite
  AC2: list_portfolios returns nested structure
  AC3: update_project (PATCH) persists correctly
  AC4: delete_portfolio cascades to projects
  AC5: Existing test suite unaffected (scoped to this module via isolated DB)
"""

import pytest
import memory.db as db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def in_memory_db(tmp_path, monkeypatch):
    """Redirect all DB operations to an isolated temp database per test."""
    db_path = tmp_path / "test_hierarchy.db"
    monkeypatch.setattr(db, "_DB_PATH", db_path)
    yield db_path


# ── AC1: Portfolio creation writes to SQLite ──────────────────────────────────

def test_create_portfolio_writes_to_db():
    result = db.create_portfolio("Payments Platform")
    assert result["id"] > 0
    assert result["name"] == "Payments Platform"
    assert result["created_at"]

    portfolios = db.list_portfolios()
    assert len(portfolios) == 1
    assert portfolios[0]["name"] == "Payments Platform"


# ── AC1: Project creation writes to SQLite with correct FK ───────────────────

def test_create_project_under_portfolio():
    portfolio = db.create_portfolio("Core Services")
    project = db.create_project(
        portfolio_id=portfolio["id"],
        name="Payment Gateway",
        repo_url="https://github.com/acme/gateway",
        business_tier="Tier 1",
        user_type="external_customers",
    )
    assert project["id"] > 0
    assert project["portfolio_id"] == portfolio["id"]
    assert project["name"] == "Payment Gateway"
    assert project["repo_url"] == "https://github.com/acme/gateway"
    assert project["business_tier"] == "Tier 1"


# ── AC2: list_portfolios returns nested structure ─────────────────────────────

def test_list_portfolios_returns_nested_structure():
    p1 = db.create_portfolio("Portfolio A")
    p2 = db.create_portfolio("Portfolio B")
    db.create_project(p1["id"], "Project X", repo_url="https://github.com/x")
    db.create_project(p1["id"], "Project Y")
    db.create_project(p2["id"], "Project Z")

    portfolios = db.list_portfolios()
    assert len(portfolios) == 2

    by_name = {p["name"]: p for p in portfolios}
    assert len(by_name["Portfolio A"]["projects"]) == 2
    assert len(by_name["Portfolio B"]["projects"]) == 1

    names_a = {pr["name"] for pr in by_name["Portfolio A"]["projects"]}
    assert names_a == {"Project X", "Project Y"}


# ── AC3: update_project persists repo_url change ─────────────────────────────

def test_patch_project_repo_url():
    portfolio = db.create_portfolio("Test Portfolio")
    project = db.create_project(portfolio["id"], "My Service")
    assert project["repo_url"] is None

    db.update_project(project["id"], repo_url="https://github.com/acme/service")

    portfolios = db.list_portfolios()
    updated = portfolios[0]["projects"][0]
    assert updated["repo_url"] == "https://github.com/acme/service"


def test_patch_project_partial_update_leaves_other_fields_unchanged():
    portfolio = db.create_portfolio("Test Portfolio")
    project = db.create_project(
        portfolio["id"], "Auth Service",
        business_tier="Tier 1", user_type="external_customers",
    )
    db.update_project(project["id"], repo_url="https://github.com/acme/auth")

    portfolios = db.list_portfolios()
    updated = portfolios[0]["projects"][0]
    assert updated["business_tier"] == "Tier 1"       # unchanged
    assert updated["user_type"] == "external_customers"  # unchanged
    assert updated["repo_url"] == "https://github.com/acme/auth"


# ── AC4: delete_portfolio cascades to its projects ───────────────────────────

def test_delete_portfolio_cascades_to_projects():
    p1 = db.create_portfolio("To Delete")
    p2 = db.create_portfolio("To Keep")
    db.create_project(p1["id"], "Child Project A")
    db.create_project(p1["id"], "Child Project B")
    db.create_project(p2["id"], "Survivor Project")

    db.delete_portfolio(p1["id"])

    portfolios = db.list_portfolios()
    assert len(portfolios) == 1
    assert portfolios[0]["name"] == "To Keep"
    assert len(portfolios[0]["projects"]) == 1
    assert portfolios[0]["projects"][0]["name"] == "Survivor Project"


# ── delete_project removes only that row ─────────────────────────────────────

def test_delete_project_removes_single_row():
    portfolio = db.create_portfolio("Portfolio")
    p1 = db.create_project(portfolio["id"], "Keep Me")
    p2 = db.create_project(portfolio["id"], "Delete Me")

    db.delete_project(p2["id"])

    portfolios = db.list_portfolios()
    projects = portfolios[0]["projects"]
    assert len(projects) == 1
    assert projects[0]["name"] == "Keep Me"
