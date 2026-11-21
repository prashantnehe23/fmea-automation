"""
api/policy.py — B-015 (ADR-027): who may call what.

One table maps every route to a permission, and one dependency (`enforce`, applied to the whole app)
checks the session, the CSRF header and the role before any handler runs. A route that is missing
from POLICY is refused, and a test fails when one is added without an entry, so the rule cannot
erode silently.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from core import auth

SESSION_COOKIE = "fmea_session"
CSRF_HEADER, CSRF_VALUE = "x-requested-with", "fmea"

ALL = {"read", "scan", "chat", "score", "hierarchy", "hierarchy_delete", "settings", "users", "pr_check", "ci_config"}
TOKEN_PERMISSIONS = {"pr_check"}          # what an API token (CI) may do, and nothing else
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin":             ALL,
    "security_engineer": {"read", "scan", "chat", "score", "hierarchy", "hierarchy_delete", "pr_check", "ci_config"},
    "risk_manager":      {"read", "chat", "hierarchy", "hierarchy_delete"},
    "developer":         {"read", "scan", "chat", "hierarchy", "pr_check"},
    "viewer":            {"read"},
}

POLICY: dict[tuple[str, str], str] = {
    # public: health, sign-in, and the page shell
    ("GET", "/api/health"): "public",
    ("GET", "/api/auth/status"): "public",
    ("POST", "/api/auth/setup"): "public",
    ("POST", "/api/auth/login"): "public",
    ("POST", "/api/auth/logout"): "public",
    ("GET", "/api/auth/oidc/login"): "public",
    ("GET", "/api/auth/oidc/callback"): "public",
    ("GET", "/{path:path}"): "public",
    # any signed-in user
    ("GET", "/api/auth/me"): "read",
    ("GET", "/api/scan/{scan_id}"): "read",
    ("GET", "/api/workspace"): "read",
    ("GET", "/api/workspace/{workspace_id}/scans"): "read",
    ("GET", "/api/workspace/{workspace_id}/scenarios"): "read",
    ("GET", "/api/workspace/{workspace_id}/findings"): "read",
    ("GET", "/api/portfolios"): "read",
    ("GET", "/api/projects/{project_id}/latest-scan"): "read",
    ("GET", "/api/remediate/{remediation_id}"): "read",
    ("GET", "/api/eval/history/{workspace_id}"): "read",
    ("GET", "/api/telemetry/{workspace_id}"): "read",
    ("GET", "/api/scoring/adjustments/{workspace_id}"): "read",
    ("GET", "/api/settings/models"): "read",
    ("GET", "/api/settings/model"): "read",
    ("GET", "/api/settings/reasoning"): "read",
    ("GET", "/api/settings/providers"): "read",
    ("GET", "/api/chat/{workspace_id}"): "read",
    # scans and fixes
    ("POST", "/api/scan"): "scan",
    ("POST", "/api/github/scan"): "scan",
    ("POST", "/api/github/preview"): "scan",
    ("POST", "/api/remediate"): "scan",
    # chat
    ("POST", "/api/chat"): "chat",
    ("POST", "/api/chat/stream"): "chat",
    ("POST", "/api/chat/proposals/{proposal_id}/dismiss"): "chat",
    # score changes (including unlocking a locked scenario)
    ("POST", "/api/scoring/adjustment"): "score",
    ("POST", "/api/workspace/{workspace_id}/findings/state"): "score",
    ("DELETE", "/api/workspace/{workspace_id}/scenarios"): "score",
    ("POST", "/api/chat/proposals/{proposal_id}/apply"): "score",
    # portfolios and projects
    ("POST", "/api/workspace"): "hierarchy",
    ("POST", "/api/portfolios"): "hierarchy",
    ("POST", "/api/portfolios/{portfolio_id}/projects"): "hierarchy",
    ("PATCH", "/api/projects/{project_id}"): "hierarchy",
    ("DELETE", "/api/portfolios/{portfolio_id}"): "hierarchy_delete",
    ("DELETE", "/api/projects/{project_id}"): "hierarchy_delete",
    ("DELETE", "/api/workspace/{workspace_id}/sources"): "hierarchy_delete",
    # settings and keys
    ("PATCH", "/api/settings/model"): "settings",
    ("PATCH", "/api/settings/reasoning"): "settings",
    ("PUT", "/api/settings/providers/{provider_id}/key"): "settings",
    ("DELETE", "/api/settings/providers/{provider_id}/key"): "settings",
    ("POST", "/api/settings/providers/{provider_id}/verify"): "settings",
    ("GET", "/api/settings/repo-credentials"): "settings",
    ("PUT", "/api/settings/repo-credentials"): "settings",
    ("DELETE", "/api/settings/repo-credentials"): "settings",
    ("POST", "/api/settings/pricing/refresh"): "settings",
    # pull-request check and the tokens CI uses (B-012)
    ("POST", "/api/pr-check"): "pr_check",
    ("GET", "/api/projects/{project_id}/pr-check"): "read",
    ("PUT", "/api/projects/{project_id}/pr-check"): "ci_config",
    ("GET", "/api/tokens"): "settings",
    ("POST", "/api/tokens"): "settings",
    ("DELETE", "/api/tokens/{token_id}"): "settings",
    # users
    ("GET", "/api/users"): "users",
    ("POST", "/api/users"): "users",
    ("PATCH", "/api/users/{user_id}"): "users",
}


def enforce(request: Request):
    """App-wide dependency: 401 without a session, 403 without the CSRF header or the role."""
    route = request.scope.get("route")
    method = "GET" if request.method == "HEAD" else request.method
    permission = POLICY.get((method, getattr(route, "path", "")))
    if permission is None:
        raise HTTPException(403, "This route has no access policy.")
    if permission == "public":
        return None
    bearer = request.headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        token_user = auth.api_token_user(bearer[7:].strip())          # CI: no cookie, no CSRF header
        if token_user is None:
            raise HTTPException(401, "Invalid or revoked token.")
        if permission not in TOKEN_PERMISSIONS:
            raise HTTPException(403, "A token may only run the pull-request check.")
        request.state.user = token_user
        return token_user
    user = auth.session_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    if method not in ("GET", "OPTIONS") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(403, "Missing request header.")
    if permission not in ROLE_PERMISSIONS.get(user["role"], set()):
        raise HTTPException(403, "Your role does not allow this.")
    request.state.user = user
    return user
