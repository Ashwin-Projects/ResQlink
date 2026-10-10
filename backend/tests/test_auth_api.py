"""Live API tests for authentication and authorization (migration 0015).

Run against the REAL database (DATABASE_URL = resqlink_app login,
ADMIN_DATABASE_URL = admin for setup); skipped when it is unreachable.

    cd backend
    DATABASE_URL=postgresql+asyncpg://resqlink_app:<APP_DB_PASSWORD>@localhost:5432/resqlink \\
    ADMIN_DATABASE_URL=postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink \\
        python -m pytest -o asyncio_mode=auto tests/test_auth_api.py -v
"""
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import app
from app.security.jwt import create_access_token
from live_support import (COORDINATOR, DEMO_PASSWORD, OWNER_A, OWNER_B, REQUESTER_A, REQUESTER_B,
                          admin_engine, live_db_available, login_headers)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api():
    err = await live_db_available("SELECT 1 FROM app_users LIMIT 1")
    if err is not None:  # pragma: no cover - environment dependent
        pytest.skip(f"Live PostgreSQL (with migration 0015) not available: {err}")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await admin_engine.dispose()


async def admin(sql, **p):
    async with admin_engine.begin() as conn:
        return (await conn.execute(text(sql), p)).scalar()


@pytest.mark.parametrize("username,role", [(COORDINATOR, "coordinator"), (OWNER_A, "owner"), (OWNER_B, "owner"),
                                           (REQUESTER_A, "requester"), (REQUESTER_B, "requester")])
async def test_login_success_returns_signed_jwt(api, username, role):
    res = await api.post("/api/v1/auth/login", json={"username": username, "password": DEMO_PASSWORD})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token_type"] == "bearer" and body["user"]["role"] == role and body["expires_in"] > 0
    me = await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["role"] == role and me.json()["subject_id"] == body["user"]["subject_id"]


async def test_invalid_credentials(api):
    bad = await api.post("/api/v1/auth/login", json={"username": COORDINATOR, "password": "wrong"})
    unknown = await api.post("/api/v1/auth/login", json={"username": "nobody.here", "password": "wrong"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"] == "Invalid username or password"
    assert (await api.post("/api/v1/auth/login", json={"username": COORDINATOR, "password": DEMO_PASSWORD,
                                                       "role": "coordinator"})).status_code == 422   # no role picking
    await admin("UPDATE app_users SET failed_attempts = 0, locked_until = NULL WHERE username = :u", u=COORDINATOR)


async def test_form_login_for_swagger(api):
    res = await api.post("/api/v1/auth/token", data={"username": REQUESTER_A, "password": DEMO_PASSWORD})
    assert res.status_code == 200 and res.json()["user"]["role"] == "requester"


async def test_lockout_after_five_failures(api):
    for _ in range(5):
        await api.post("/api/v1/auth/login", json={"username": OWNER_B, "password": "nope"})
    res = await api.post("/api/v1/auth/login", json={"username": OWNER_B, "password": DEMO_PASSWORD})
    assert res.status_code == 429 and "retry-after" in res.headers
    await admin("UPDATE app_users SET failed_attempts = 0, locked_until = NULL WHERE username = :u", u=OWNER_B)


async def test_missing_invalid_and_expired_tokens(api):
    assert (await api.get("/api/v1/requests")).status_code == 401
    assert (await api.get("/api/v1/requests", headers={"Authorization": "Bearer junk"})).status_code == 401
    good = await login_headers(api, REQUESTER_A)
    uid = (await api.get("/api/v1/auth/me", headers=good)).json()["user_id"]
    expired = create_access_token("f1111111-1111-1111-1111-111111111111", "requester", timedelta(seconds=-60), user_id=uid)
    res = await api.get("/api/v1/requests", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401 and "expired" in res.json()["detail"]


async def test_deactivated_account_token_rejected(api):
    headers = await login_headers(api, REQUESTER_B)
    await admin("UPDATE app_users SET is_active = false WHERE username = :u", u=REQUESTER_B)
    try:
        assert (await api.get("/api/v1/requests", headers=headers)).status_code == 401
    finally:
        await admin("UPDATE app_users SET is_active = true WHERE username = :u", u=REQUESTER_B)


@pytest.mark.parametrize("method,path,role_ok", [
    ("post", "/api/v1/match/engine/full-rescan", "coordinator"),
    ("get", "/api/v1/audit/activity-feed", "coordinator"),
    ("get", "/api/v1/hazards/rematch-runs", "coordinator"),
    ("get", "/api/v1/requesters", "coordinator"),
])
async def test_coordinator_only_endpoints(api, method, path, role_ok):
    for user in (OWNER_A, REQUESTER_A):
        res = await getattr(api, method)(path, headers=await login_headers(api, user))
        assert res.status_code == 403, (user, path, res.text)


async def test_requester_contact_privacy(api):
    coord, req_a, owner = (await login_headers(api, COORDINATOR), await login_headers(api, REQUESTER_A),
                           await login_headers(api, OWNER_A))
    phone_b = await admin("SELECT contact_phone FROM requesters WHERE requester_id = 'f2222222-2222-2222-2222-222222222222'")
    listed = await api.get("/api/v1/requesters", headers=coord)
    assert listed.status_code == 200 and all(r["contact_masked"] for r in listed.json())
    assert phone_b not in listed.text
    detail = await api.get("/api/v1/requesters/f2222222-2222-2222-2222-222222222222", headers=coord)
    assert detail.status_code == 200 and detail.json()["contact_phone"] == phone_b
    assert (await api.get("/api/v1/requesters/f2222222-2222-2222-2222-222222222222", headers=req_a)).status_code == 404
    assert (await api.get("/api/v1/requesters/f2222222-2222-2222-2222-222222222222", headers=owner)).status_code == 403
    me = await api.get("/api/v1/requesters/me", headers=req_a)
    assert me.status_code == 200 and me.json()["contact_masked"] is False
    upd = await api.patch("/api/v1/requesters/me", json={"contact_phone": "+91 98200 00042"}, headers=req_a)
    assert upd.status_code == 200 and upd.json()["contact_phone"] == "+91 98200 00042"
    assert (await api.patch("/api/v1/requesters/me", json={"verified_flag": False}, headers=req_a)).status_code == 422


async def test_owner_sees_no_requests_on_map_or_dashboard(api):
    owner = await login_headers(api, OWNER_A)
    assert (await api.get("/api/v1/map/requests", headers=owner)).json() == []
    stats = (await api.get("/api/v1/dashboard/stats", headers=owner)).json()
    assert stats["scope"] == "owner" and stats["requests"] is None and stats["active_reservations"] is None
