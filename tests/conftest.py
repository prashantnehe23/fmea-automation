"""
Shared test setup (B-015).

Every API route requires a session. Most existing tests exercise route logic, not sign-in, so they
run as a signed-in admin through FastAPI's dependency override (test-only; production has no
switch that disables authentication). Tests of the sign-in itself ask for the `real_auth` fixture.
"""

import pytest
from fastapi import Request


def _fake_admin(request: Request):
    user = {"id": 0, "username": "test-admin", "display_name": "Test Admin", "role": "admin"}
    request.state.user = user
    return user


@pytest.fixture(autouse=True)
def _signed_in_as_admin(request):
    from api.main import app
    from api.policy import enforce

    if "real_auth" in request.fixturenames:
        yield
        return
    app.dependency_overrides[enforce] = _fake_admin
    yield
    app.dependency_overrides.pop(enforce, None)


@pytest.fixture
def real_auth():
    """Marker: run the test against the real sign-in and policy."""
    return True
