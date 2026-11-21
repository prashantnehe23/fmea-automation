"""
B-015 — OpenID Connect sign-in (ADR-027) against a stand-in identity provider.

The provider's two network calls are replaced; the ID token is a real RS256 JWT signed with a key
the test generates, so signature, issuer, audience, expiry and nonce checks run for real.
"""

import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

import core.oidc as oidc
import memory.db as db

ISSUER, CLIENT = "https://idp.example.com", "fmea-client"
CSRF = {"X-Requested-With": "fmea"}


@pytest.fixture
def idp(real_auth, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fmea.db")
    monkeypatch.setenv("FMEA_COOKIE_SECURE", "0")
    for k, v in {"FMEA_OIDC_ISSUER": ISSUER, "FMEA_OIDC_CLIENT_ID": CLIENT, "FMEA_OIDC_CLIENT_SECRET": "s",
                 "FMEA_OIDC_REDIRECT_URI": "https://fmea.example.com/api/auth/oidc/callback",
                 "FMEA_OIDC_ROLE_MAP": '{"sec-team": "security_engineer", "everyone": "developer"}'}.items():
        monkeypatch.setenv(k, v)
    key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    state = SimpleState(key)

    def get_json(url):
        if url.endswith("openid-configuration"):
            return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/auth", "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks"}
        return {"keys": [key.as_dict(private=False)]}

    def post_form(url, data):
        state.token_request = data
        claims = {"iss": ISSUER, "aud": CLIENT, "sub": "u-1", "exp": int(time.time()) + 300,
                  "nonce": state.nonce, "preferred_username": "sam", "name": "Sam S", "groups": state.groups,
                  **state.overrides}
        return {"id_token": jwt.encode({"alg": "RS256", "kid": "k1"}, claims, state.signing_key or key)}

    monkeypatch.setattr(oidc, "_get_json", get_json)
    monkeypatch.setattr(oidc, "_post_form", post_form)
    oidc._discovery_cache.clear()
    from api.main import app
    state.client = TestClient(app, headers=CSRF, follow_redirects=False)
    return state


class SimpleState:
    def __init__(self, key):
        self.key, self.nonce, self.groups, self.overrides, self.signing_key = key, None, ["sec-team"], {}, None

    def start(self):
        r = self.client.get("/api/auth/oidc/login")
        assert r.status_code == 302, r.text
        q = parse_qs(urlparse(r.headers["location"]).query)
        self.nonce = q["nonce"][0]
        return q

    def finish(self, state=None, code="abc"):
        q = self.start() if state is None else None
        return self.client.get("/api/auth/oidc/callback", params={"code": code, "state": state or q["state"][0]})


def test_login_redirects_with_pkce_and_state(idp):
    q = idp.start()
    assert q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"]
    assert q["client_id"] == [CLIENT] and q["state"] and q["nonce"]


def test_successful_sign_in_creates_a_user_with_the_mapped_role(idp):
    r = idp.finish()
    assert r.status_code == 302 and r.headers["location"] == "/"
    me = idp.client.get("/api/auth/me").json()
    assert me["username"] == "sam" and me["role"] == "security_engineer" and me["sign_in"] == "single sign-on"
    assert "code_verifier" in idp.token_request                              # PKCE verifier sent to the token endpoint


def test_highest_ranked_group_wins_and_roles_follow_the_provider(idp):
    idp.groups = ["everyone", "sec-team"]
    idp.finish()
    assert idp.client.get("/api/auth/me").json()["role"] == "security_engineer"
    idp.groups = ["everyone"]
    idp.finish()
    assert idp.client.get("/api/auth/me").json()["role"] == "developer"       # re-read at each sign-in
    idp.groups = []
    idp.finish()
    assert idp.client.get("/api/auth/me").json()["role"] == "viewer"          # default role


def test_state_is_single_use_and_unknown_state_is_refused(idp):
    q = idp.start()
    ok = idp.client.get("/api/auth/oidc/callback", params={"code": "c", "state": q["state"][0]})
    assert ok.headers["location"] == "/"
    replay = idp.client.get("/api/auth/oidc/callback", params={"code": "c", "state": q["state"][0]})
    assert "sign_in_error" in replay.headers["location"]
    assert "sign_in_error" in idp.client.get("/api/auth/oidc/callback", params={"code": "c", "state": "forged"}).headers["location"]


@pytest.mark.parametrize("override", [{"iss": "https://evil.example.com"}, {"aud": "other-client"},
                                      {"exp": 1}, {"nonce": "wrong"}])
def test_bad_id_token_claims_are_refused(idp, override):
    idp.overrides = override
    r = idp.finish()
    assert "sign_in_error" in r.headers["location"]
    assert idp.client.get("/api/auth/me").status_code == 401


def test_token_signed_with_another_key_is_refused(idp):
    idp.signing_key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    assert "sign_in_error" in idp.finish().headers["location"]
    assert idp.client.get("/api/auth/me").status_code == 401


def test_disabled_sso_user_cannot_sign_in(idp):
    idp.finish()
    uid = idp.client.get("/api/auth/me").json()["id"]
    conn = db.get_db(); conn.execute("UPDATE users SET disabled=1 WHERE id=?", (uid,)); conn.commit(); conn.close()
    assert "sign_in_error" in idp.finish().headers["location"]


def test_sso_routes_are_404_when_not_configured(real_auth, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fmea.db")
    monkeypatch.delenv("FMEA_OIDC_ISSUER", raising=False)
    from api.main import app
    c = TestClient(app, headers=CSRF, follow_redirects=False)
    assert c.get("/api/auth/oidc/login").status_code == 404
    assert c.get("/api/auth/status").json()["oidc_enabled"] is False


def test_callback_must_come_from_the_browser_that_started_the_sign_in(idp):
    q = idp.start()                                         # this browser holds the state cookie
    attacker_state = q["state"][0]
    victim = TestClient(idp.client.app, headers=CSRF, follow_redirects=False)       # no cookie
    r = victim.get("/api/auth/oidc/callback", params={"code": "c", "state": attacker_state})
    assert "sign_in_error" in r.headers["location"]
    assert victim.get("/api/auth/me").status_code == 401


def test_issuer_mismatch_and_plain_http_issuer_are_refused(idp, monkeypatch):
    real = oidc._get_json
    monkeypatch.setattr(oidc, "_get_json", lambda url: {**real(url), "issuer": "https://other.example.com"}
                        if url.endswith("openid-configuration") else real(url))
    oidc._discovery_cache.clear()
    assert idp.client.get("/api/auth/oidc/login").status_code == 502
    monkeypatch.setenv("FMEA_OIDC_ISSUER", "http://idp.example.com")
    oidc._discovery_cache.clear()
    assert idp.client.get("/api/auth/oidc/login").status_code == 502
