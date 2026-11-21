"""
api/routers/auth.py — B-015 (ADR-027): sign-in, sign-out, first-run setup and user management.

GET  /api/auth/status      — public: whether setup is needed, demo mode, single sign-on available
POST /api/auth/setup       — public until the first administrator exists
POST /api/auth/login       — public: password sign-in, sets the session cookie
POST /api/auth/logout      — ends the session
GET  /api/auth/me          — the signed-in user
GET|POST /api/users, PATCH /api/users/{id} — administrators only
"""

import os
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.policy import SESSION_COOKIE
from core import auth

router = APIRouter(tags=["auth"])
OIDC_STATE_COOKIE = "fmea_oidc_state"


def _sign_in_error(message: str) -> RedirectResponse:
    response = RedirectResponse("/?sign_in_error=" + quote_plus(message), status_code=302)
    response.delete_cookie(OIDC_STATE_COOKIE, path="/api/auth/oidc")
    return response


class Credentials(BaseModel):
    username: str
    password: str


class SetupIn(Credentials):
    display_name: str | None = None
    setup_token: str | None = None


class UserIn(Credentials):
    role: str
    display_name: str | None = None


class UserPatch(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    password: str | None = None


def _fail(exc: auth.AuthError):
    raise HTTPException(exc.status, str(exc))


def set_session_cookie(request: Request, response: Response, user_id: int) -> None:
    # Secure unless explicitly turned off for plain-http local development: behind a TLS proxy the app sees http
    secure = request.url.scheme == "https" or os.environ.get("FMEA_COOKIE_SECURE", "1") != "0"
    response.set_cookie(SESSION_COOKIE, auth.create_session(user_id), max_age=auth.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=secure, path="/")


@router.get("/api/auth/status")
def status():
    from core.oidc import oidc_enabled
    return {"setup_required": not auth.has_active_admin(),
            "setup_token_required": auth.setup_token_required(),
            "demo_mode": os.environ.get("FMEA_DEMO_MODE") == "1",
            "oidc_enabled": oidc_enabled()}


@router.post("/api/auth/setup", status_code=201)
def setup(body: SetupIn, request: Request, response: Response):
    try:
        user = auth.create_first_admin(body.username, body.password, body.display_name, body.setup_token)
    except auth.AuthError as exc:
        _fail(exc)
    set_session_cookie(request, response, user["id"])
    return user


@router.post("/api/auth/login")
def login(body: Credentials, request: Request, response: Response):
    try:
        user = auth.authenticate(body.username, body.password, request.client.host if request.client else "")
    except auth.AuthError as exc:
        _fail(exc)
    if user is None:
        raise HTTPException(401, "Wrong username or password.")
    set_session_cookie(request, response, user["id"])
    auth.record_event(user, "sign_in")
    return user


@router.get("/api/auth/oidc/login")
def oidc_login():
    from core import oidc
    if not oidc.oidc_enabled():
        raise HTTPException(404, "Single sign-on is not configured.")
    try:
        url, state = oidc.begin_login()
    except Exception:
        raise HTTPException(502, "Could not reach the identity provider.")
    response = RedirectResponse(url, status_code=302)
    # Binds the callback to the browser that started the sign-in (a forged callback link has no such cookie)
    response.set_cookie(OIDC_STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax",
                        secure=os.environ.get("FMEA_COOKIE_SECURE", "1") != "0", path="/api/auth/oidc")
    return response


@router.get("/api/auth/oidc/callback")
def oidc_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    from core import oidc
    if not oidc.oidc_enabled():
        raise HTTPException(404, "Single sign-on is not configured.")
    if state and request.cookies.get(OIDC_STATE_COOKIE) != state:
        return _sign_in_error("The sign-in was not started in this browser. Start again.")
    if error or not code or not state:
        return _sign_in_error("The identity provider did not complete the sign-in.")
    try:
        user = oidc.complete_login(code, state)
    except oidc.OidcError as exc:
        return _sign_in_error(str(exc))
    response = RedirectResponse("/", status_code=302)
    set_session_cookie(request, response, user["id"])
    response.delete_cookie(OIDC_STATE_COOKIE, path="/api/auth/oidc")
    auth.record_event(user, "sign_in", "single sign-on")
    return response


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.delete_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"signed_out": True}


@router.get("/api/auth/me")
def me(request: Request):
    return request.state.user


@router.get("/api/users")
def users():
    return auth.list_users()


@router.post("/api/users", status_code=201)
def add_user(body: UserIn, request: Request):
    try:
        user = auth.create_user(body.username, body.password, body.role, body.display_name)
    except auth.AuthError as exc:
        _fail(exc)
    auth.record_event(request.state.user, "user_created", f"{user['username']} as {user['role']}")
    return user


@router.patch("/api/users/{user_id}")
def change_user(user_id: int, body: UserPatch, request: Request):
    try:
        user = auth.update_user(user_id, role=body.role, disabled=body.disabled, password=body.password)
    except auth.AuthError as exc:
        _fail(exc)
    changes = [k for k, v in (("role", body.role), ("disabled", body.disabled), ("password", body.password)) if v is not None]
    auth.record_event(request.state.user, "user_changed", f"{user['username']}: {', '.join(changes)}")
    return user
