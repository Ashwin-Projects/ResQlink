"""Live tests: public sign-up (POST /api/v1/auth/register) and role-checked sign-in.

These create real accounts, so they run ONLY when explicitly enabled against a
disposable database that has migration 0016 (fn_auth_register):

    cd backend
    RESQLINK_SIGNUP_TESTS=1 \
    DATABASE_URL=postgresql+asyncpg://resqlink_app:<APP_DB_PASSWORD>@localhost:<port>/resqlink \
    ADMIN_DATABASE_URL=postgresql+asyncpg://resqlink:<password>@localhost:<port>/resqlink \
        python -m pytest -o asyncio_mode=auto tests/test_registration_api.py -v
"""
import os
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import exc, text

from app.main import app
from app.db.session import auth_session
from live_support import (COORDINATOR, DEMO_PASSWORD, USERNAME_BY_SUBJECT, admin_engine, live_db_available,
                          login_headers)

pytestmark = pytest.mark.asyncio
PASSWORD = "Signup-Test-2026"   # test-only accounts in a disposable database


@pytest_asyncio.fixture
async def api():
    if os.environ.get("RESQLINK_SIGNUP_TESTS") != "1":
        pytest.skip("sign-up tests create accounts; set RESQLINK_SIGNUP_TESTS=1 against a disposable database")
    err = await live_db_available("SELECT 'fn_auth_register'::regproc")
    if err is not None:  # pragma: no cover - environment dependent
        pytest.skip(f"Database with migration 0016 not available: {err}")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await admin_engine.dispose()


async def admin_row(sql, **p):
    async with admin_engine.begin() as conn:
        return (await conn.execute(text(sql), p)).mappings().first()


def new_username(prefix="pytest-signup"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def signup(role, username, **extra):
    body = {"role": role, "username": username, "password": PASSWORD, "display_name": f"Test {role}",
            "contact_phone": "+91 98765 43210", "contact_email": f"{username}@example.org"}
    body.update(extra)
    return body


async def test_requester_signs_up_signs_in_and_can_use_its_role(api):
    username = new_username()
    res = await api.post("/api/v1/auth/register", json=signup("requester", username.upper()))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "active" and body["role"] == "requester" and body["username"] == username

    row = await admin_row("""SELECT u.is_active, u.role, u.password_hash, r.verified_flag, r.requester_type
                             FROM app_users u JOIN requesters r ON r.requester_id = u.requester_id
                             WHERE u.username = :u""", u=username)
    assert row["is_active"] and row["role"] == "requester"
    assert row["password_hash"].startswith("pbkdf2_sha256$") and PASSWORD not in row["password_hash"]
    assert row["verified_flag"] is False and row["requester_type"] == "individual"

    login = await api.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD,
                                                        "expected_role": "requester"})
    assert login.status_code == 200 and login.json()["user"]["role"] == "requester"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = (await api.get("/api/v1/auth/me", headers=headers)).json()

    # The new account works under its own RLS role: it can file a request for itself only.
    zone = (await api.get("/api/v1/requests/form-options", headers=headers)).json()["zones"][0]
    created = await api.post("/api/v1/requests", headers=headers, json={
        "requester_id": me["subject_id"], "zone_id": zone["zone_id"], "resource_type_needed": "medical_supply",
        "quantity_requested": 1, "urgency_level": "low", "idempotency_key": f"pytest-signup-{uuid.uuid4()}"})
    assert created.status_code == 201, created.text
    other = next(s for s in USERNAME_BY_SUBJECT if USERNAME_BY_SUBJECT[s] in ("ramesh.kumar",))
    assert (await api.post("/api/v1/requests", headers=headers, json={
        "requester_id": other, "zone_id": zone["zone_id"], "resource_type_needed": "medical_supply",
        "quantity_requested": 1, "urgency_level": "low"})).status_code == 403
    assert (await api.get("/api/v1/resources", headers=headers)).status_code == 403          # not an owner
    assert (await api.post("/api/v1/match/engine/full-rescan", headers=headers)).status_code == 403


async def test_selected_role_must_match_the_account(api):
    username = new_username()
    assert (await api.post("/api/v1/auth/register", json=signup("requester", username))).status_code == 201
    res = await api.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD,
                                                      "expected_role": "coordinator"})
    assert res.status_code == 403 and "Requester account" in res.json()["detail"]
    assert "access_token" not in res.json()
    row = await admin_row("SELECT failed_attempts, last_login_at FROM app_users WHERE username = :u", u=username)
    assert row["failed_attempts"] == 0 and row["last_login_at"] is None      # nothing recorded, no token

    demo = await api.post("/api/v1/auth/login", json={"username": COORDINATOR, "password": DEMO_PASSWORD,
                                                       "expected_role": "requester"})
    assert demo.status_code == 403
    # A client cannot pick its role: the old 'role' field is still rejected.
    assert (await api.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD,
                                                        "role": "coordinator"})).status_code == 422


async def test_owner_signup_is_pending_until_verified(api):
    username = new_username()
    res = await api.post("/api/v1/auth/register", json=signup("owner", username, owner_type="ngo"))
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "pending_approval"
    row = await admin_row("""SELECT u.is_active, u.owner_id, o.verification_status FROM app_users u
                             JOIN owners o ON o.owner_id = u.owner_id WHERE u.username = :u""", u=username)
    assert row["is_active"] is False and row["verification_status"] == "pending"

    blocked = await api.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD,
                                                          "expected_role": "owner"})
    assert blocked.status_code == 403 and "not active" in blocked.json()["detail"]
    wrong_pw = await api.post("/api/v1/auth/login", json={"username": username, "password": "wrong-password-1"})
    assert wrong_pw.status_code == 401                     # status is revealed only after a correct password

    # A coordinator verifies the organisation (done in the database; there is no approval UI).
    await admin_row("UPDATE owners SET verification_status = 'verified' WHERE owner_id = :o RETURNING 1", o=row["owner_id"])
    await admin_row("UPDATE app_users SET is_active = true WHERE username = :u RETURNING 1", u=username)
    ok = await api.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD, "expected_role": "owner"})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "owner"
    headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (await api.get("/api/v1/resources", headers=headers)).status_code == 200
    assert (await api.get("/api/v1/requests", headers=headers)).status_code == 403          # owners cannot see requests


async def test_coordinator_cannot_self_register(api):
    username = new_username()
    res = await api.post("/api/v1/auth/register", json=signup("coordinator", username))
    assert res.status_code == 403 and "administrator" in res.json()["detail"]
    assert await admin_row("SELECT 1 FROM app_users WHERE username = :u", u=username) is None

    # The database function refuses it too, even when called directly by api_auth.
    async with auth_session() as s:
        with pytest.raises(exc.DBAPIError) as err:
            await s.execute(text("SELECT * FROM fn_auth_register('coordinator', :u, 'pbkdf2_sha256$1$a$b', 'X', '9999999', NULL, NULL)"),
                            {"u": username})
        assert getattr(err.value.orig, "sqlstate", None) == "42501" or "42501" in str(err.value)
        await s.rollback()
    assert await admin_row("SELECT 1 FROM app_users WHERE username = :u", u=username) is None


async def test_duplicate_and_invalid_signups_are_rejected(api):
    username = new_username()
    assert (await api.post("/api/v1/auth/register", json=signup("requester", username))).status_code == 201
    dup = await api.post("/api/v1/auth/register", json=signup("owner", username.upper(), owner_type="private"))
    assert dup.status_code == 409 and "taken" in dup.json()["detail"]
    assert (await api.post("/api/v1/auth/register", json=signup("requester", "asha.verma"))).status_code == 409

    for bad in ({"password": "short1"}, {"password": "lettersonlylong"}, {"contact_phone": "call me"},
                {"owner_type": "ngo"}, {"is_active": True}, {"verified_flag": True},
                {"contact_email": "not-an-email"}):
        res = await api.post("/api/v1/auth/register", json=signup("requester", new_username(), **bad))
        assert res.status_code == 422, (bad, res.text)
    assert (await api.post("/api/v1/auth/register", json=signup("requester", "bad name!"))).status_code == 422
    same = new_username()
    assert (await api.post("/api/v1/auth/register", json=signup("requester", same, password=same))).status_code == 422
    assert (await api.post("/api/v1/auth/register", json=signup("owner", new_username()))).status_code == 422  # no owner_type


async def test_demo_accounts_still_sign_in_with_their_roles(api):
    for subject, username in USERNAME_BY_SUBJECT.items():
        role = {"asha.verma": "coordinator", "sdra.owner": "owner", "coastal.owner": "owner"}.get(username, "requester")
        res = await api.post("/api/v1/auth/login", json={"username": username, "password": DEMO_PASSWORD,
                                                          "expected_role": role})
        assert res.status_code == 200 and res.json()["user"]["subject_id"] == subject, (username, res.text)
    assert (await login_headers(api, COORDINATOR))["Authorization"].startswith("Bearer ")
