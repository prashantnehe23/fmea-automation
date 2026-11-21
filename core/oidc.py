"""
core/oidc.py — B-015 (ADR-027): OpenID Connect single sign-on, authorisation code flow with PKCE.

Configuration (environment):
  FMEA_OIDC_ISSUER         identity provider issuer URL (enables single sign-on)
  FMEA_OIDC_CLIENT_ID / FMEA_OIDC_CLIENT_SECRET
  FMEA_OIDC_REDIRECT_URI   https://<host>/api/auth/oidc/callback (registered with the provider)
  FMEA_OIDC_GROUPS_CLAIM   claim that lists the user's groups (default "groups")
  FMEA_OIDC_ROLE_MAP       JSON: {"group name": "role"}; the highest-ranked match wins
  FMEA_OIDC_DEFAULT_ROLE   role for users matching no group (default "viewer")

The provider is the authority for roles: they are re-read at every sign-in. The ID token's signature,
issuer, audience, expiry and nonce are all checked.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from authlib.common.security import generate_token
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from joserfc import jwt
from joserfc.jwk import KeySet

import memory.db as db
from core import auth

LOGIN_TTL_MINUTES = 10
_ROLE_RANK = {role: i for i, role in enumerate(reversed(auth.ROLES))}     # admin is highest


class OidcError(Exception):
    """Sign-in failed for a reason the user should be told in plain words."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def oidc_enabled() -> bool:
    return bool(_env("FMEA_OIDC_ISSUER"))


# Network access, kept in two small functions so tests can stand in for the identity provider.
def _get_json(url: str) -> dict:
    r = httpx.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def _post_form(url: str, data: dict) -> dict:
    r = httpx.post(url, data=data, timeout=10)
    if r.status_code >= 400:
        raise OidcError("The identity provider rejected the sign-in.")
    return r.json()


_discovery_cache: dict[str, tuple[float, dict]] = {}


def _discovery() -> dict:
    issuer = _env("FMEA_OIDC_ISSUER").rstrip("/")
    cached = _discovery_cache.get(issuer)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    if not (issuer.startswith("https://") or issuer.startswith("http://localhost")):
        raise OidcError("The identity provider must use https.")
    doc = _get_json(f"{issuer}/.well-known/openid-configuration")
    if str(doc.get("issuer", "")).rstrip("/") != issuer:
        raise OidcError("The identity provider's issuer does not match the configuration.")
    _discovery_cache[issuer] = (time.time(), doc)
    return doc


def begin_login() -> tuple[str, str]:
    """Remember state, nonce and PKCE verifier server-side; return (the provider's login URL, state)."""
    cfg = _discovery()
    state, nonce, verifier = generate_token(32), generate_token(32), generate_token(64)
    now = datetime.now()
    with db._lock:
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM oidc_logins WHERE created_at < ?",
                         ((now - timedelta(minutes=LOGIN_TTL_MINUTES)).isoformat(),))
            conn.execute("INSERT INTO oidc_logins (state, nonce, code_verifier, created_at) VALUES (?, ?, ?, ?)",
                         (state, nonce, verifier, now.isoformat()))
            conn.commit()
        finally:
            conn.close()
    query = urlencode({
        "response_type": "code", "client_id": _env("FMEA_OIDC_CLIENT_ID"), "redirect_uri": _env("FMEA_OIDC_REDIRECT_URI"),
        "scope": "openid profile email groups", "state": state, "nonce": nonce,
        "code_challenge": create_s256_code_challenge(verifier), "code_challenge_method": "S256",
    })
    return f"{cfg['authorization_endpoint']}?{query}", state


def _take_login(state: str) -> dict:
    with db._lock:
        conn = db.get_db()
        try:
            row = conn.execute("SELECT * FROM oidc_logins WHERE state=?", (state,)).fetchone()
            conn.execute("DELETE FROM oidc_logins WHERE state=?", (state,))        # single use
            conn.commit()
        finally:
            conn.close()
    if row is None or datetime.fromisoformat(row["created_at"]) < datetime.now() - timedelta(minutes=LOGIN_TTL_MINUTES):
        raise OidcError("The sign-in expired or was not started here. Start again.")
    return dict(row)


def _role_for(claims: dict) -> str:
    try:
        mapping = json.loads(_env("FMEA_OIDC_ROLE_MAP") or "{}")
    except ValueError:
        mapping = {}
    groups = claims.get(_env("FMEA_OIDC_GROUPS_CLAIM", "groups")) or []
    if isinstance(groups, str):
        groups = [groups]
    roles = [mapping[g] for g in groups if mapping.get(g) in auth.ROLES]
    default = _env("FMEA_OIDC_DEFAULT_ROLE", "viewer")
    roles.append(default if default in auth.ROLES else "viewer")
    return max(roles, key=lambda r: _ROLE_RANK[r])


def complete_login(code: str, state: str) -> dict:
    """Finish the sign-in: returns the local user for a verified ID token."""
    login = _take_login(state)
    cfg = _discovery()
    token = _post_form(cfg["token_endpoint"], {
        "grant_type": "authorization_code", "code": code, "redirect_uri": _env("FMEA_OIDC_REDIRECT_URI"),
        "client_id": _env("FMEA_OIDC_CLIENT_ID"), "client_secret": _env("FMEA_OIDC_CLIENT_SECRET"),
        "code_verifier": login["code_verifier"],
    })
    id_token = token.get("id_token")
    if not id_token:
        raise OidcError("The identity provider did not return an ID token.")
    try:
        decoded = jwt.decode(id_token, KeySet.import_key_set(_get_json(cfg["jwks_uri"])))
        jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": _env("FMEA_OIDC_ISSUER").rstrip("/")},
            aud={"essential": True, "value": _env("FMEA_OIDC_CLIENT_ID")},
            exp={"essential": True}, sub={"essential": True},
            nonce={"essential": True, "value": login["nonce"]},
        ).validate(decoded.claims)
    except Exception as exc:
        raise OidcError("The identity provider's sign-in could not be verified.") from exc
    return _local_user(decoded.claims)


def _local_user(claims: dict) -> dict:
    subject, role = str(claims["sub"]), _role_for(claims)
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT id, disabled FROM users WHERE oidc_subject=?", (subject,)).fetchall()
    finally:
        conn.close()
    if rows:
        if rows[0]["disabled"]:
            raise OidcError("This account is disabled. Ask an administrator.")
        try:
            return auth.update_user(rows[0]["id"], role=role, via_idp=True)
        except auth.AuthError:                      # would remove the last administrator: keep the current role
            return auth.get_user(rows[0]["id"])     # type: ignore[return-value]
    name = str(claims.get("preferred_username") or claims.get("email") or subject)
    for candidate in (name, f"{name}-sso"):         # a local account may already use the name
        try:
            return auth.create_user(candidate, None, role, str(claims.get("name") or name), oidc_subject=subject)
        except auth.AuthError as exc:
            if exc.status != 409:
                raise OidcError(str(exc)) from exc
    raise OidcError("Could not create the account for this sign-in.")
