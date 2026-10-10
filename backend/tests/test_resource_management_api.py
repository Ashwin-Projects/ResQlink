"""Live API tests for Add / Update Resource.

Run against the REAL database in DATABASE_URL (schema.sql + seed_data.sql);
skipped automatically when it is unreachable.

    cd backend
    DATABASE_URL=postgresql+asyncpg://resqlink_app:<APP_DB_PASSWORD>@localhost:5432/resqlink \
    ADMIN_DATABASE_URL=postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink \
        python -m pytest -o asyncio_mode=auto tests/test_resource_management_api.py -v
"""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from live_support import (COORDINATOR, REQUESTER_A, admin_engine as engine, headers_for_subject,
                          live_db_available, login_headers, other_subject)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api():
    err = await live_db_available("SELECT 1 FROM resources LIMIT 1", "SELECT 'fn_log_resource_change'::regproc")
    if err is not None:  # pragma: no cover - environment dependent
        pytest.skip(f"Live PostgreSQL not available: {err}")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Default caller: the seeded coordinator, logged in through POST /api/v1/auth/login.
        client.headers.update(await login_headers(client, COORDINATOR))
        yield client
    await engine.dispose()


async def scalar(statement, **params):
    async with engine.connect() as conn:
        return (await conn.execute(text(statement), params)).scalar()


async def options(api):
    res = await api.get("/api/v1/resources/form-options")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["can_manage"] and data["owners"] and data["zones"]
    return data


def body(opts, **kw):
    return {"owner_id": opts["owners"][0]["owner_id"], "current_zone_id": opts["zones"][0]["zone_id"],
            "resource_type": "generator", "resource_subtype": "pytest genset", "quantity_total": 10,
            "unit_of_measure": "units", "mobility_class": "land", **kw}


async def test_create_persists_with_ledger_audit_and_location(api):
    opts = await options(api)
    res = await api.post("/api/v1/resources", json=body(opts))
    assert res.status_code == 201, res.text
    r = res.json()["resource"]
    rid = r["resource_id"]
    assert r["quantity_available"] == 10 and r["status"] == "available" and r["mobility_class"] == "land"
    assert r["latitude"] is not None and r["last_verified_at"] is not None
    assert await scalar("SELECT quantity_total FROM resources WHERE resource_id = :r", r=rid) == 10
    assert await scalar("SELECT count(*) FROM resource_ledger WHERE resource_id = :r AND reason = 'initial_stock'", r=rid) == 1
    assert await scalar("SELECT count(*) FROM resource_location_history WHERE resource_id = :r", r=rid) == 1
    assert await scalar("SELECT count(*) FROM allocation_history WHERE entity_type='resource' AND entity_id = :r AND action='created'", r=rid) == 1
    assert await scalar("SELECT count(*) FROM event_outbox WHERE event_type='resource_created' AND payload->>'resource_id' = :r", r=rid) == 1
    listed = (await api.get("/api/v1/resources")).json()
    assert listed[0]["resource_id"] == rid


async def test_updates_quantity_status_location_mobility(api):
    opts = await options(api)
    rid = (await api.post("/api/v1/resources", json=body(opts))).json()["resource"]["resource_id"]
    url = f"/api/v1/resources/{rid}"

    r = (await api.patch(url, json={"quantity_total": 15})).json()["resource"]
    assert r["quantity_total"] == 15 and r["quantity_available"] == 15
    r = (await api.patch(url, json={"status": "maintenance"})).json()["resource"]
    assert r["status"] == "maintenance"
    r = (await api.patch(url, json={"latitude": 13.05, "longitude": 80.25})).json()["resource"]
    assert abs(r["latitude"] - 13.05) < 1e-6
    if len(opts["zones"]) > 1:
        r = (await api.patch(url, json={"current_zone_id": opts["zones"][1]["zone_id"]})).json()["resource"]
        assert r["current_zone_id"] == opts["zones"][1]["zone_id"]
    r = (await api.patch(url, json={"mobility_class": "boat", "condition_notes": "hull patched"})).json()["resource"]
    assert r["mobility_class"] == "boat" and r["condition_notes"] == "hull patched"

    detail = (await api.get(url)).json()
    assert [e["reason"] for e in detail["ledger"]] == ["stock_adjustment", "initial_stock"]
    assert len(detail["location_history"]) >= 2
    actions = {h["action"] for h in detail["history"]}
    assert {"created", "quantity_updated", "status_changed", "updated"} <= actions
    assert detail["can_edit"] is True


async def test_stock_cannot_drop_below_quantity_in_use(api):
    opts = await options(api)
    rid = (await api.post("/api/v1/resources", json=body(opts, quantity_total=10, quantity_available=4))).json()["resource"]["resource_id"]
    res = await api.patch(f"/api/v1/resources/{rid}", json={"quantity_total": 5})
    assert res.status_code == 409 and "cannot go below 6" in res.json()["detail"]
    r = (await api.patch(f"/api/v1/resources/{rid}", json={"quantity_total": 6})).json()["resource"]
    assert r["quantity_available"] == 0 and r["status"] == "depleted"
    r = (await api.patch(f"/api/v1/resources/{rid}", json={"status": "available"})).json()["resource"]
    assert r["status"] == "depleted"   # existing DB rule: zero free stock stays depleted


@pytest.mark.parametrize("override", [
    {"quantity_total": -1}, {"quantity_total": "1.234"}, {"quantity_available": 11}, {"resource_type": "spaceship"},
    {"unit_of_measure": "boats"}, {"status": "depleted"}, {"mobility_class": "teleport"}, {"latitude": 13.0},
    {"current_zone_id": "not-a-uuid"}, {"colour": "red"},
])
async def test_invalid_create_rejected(api, override):
    opts = await options(api)
    before = await scalar("SELECT count(*) FROM resources")
    res = await api.post("/api/v1/resources", json=body(opts, **override))
    assert res.status_code == 422, res.text
    assert await scalar("SELECT count(*) FROM resources") == before


async def test_invalid_updates(api):
    opts = await options(api)
    rid = (await api.post("/api/v1/resources", json=body(opts))).json()["resource"]["resource_id"]
    url = f"/api/v1/resources/{rid}"
    assert (await api.patch(url, json={})).status_code == 422
    assert (await api.patch(url, json={"status": "allocated"})).status_code == 422
    assert (await api.patch(url, json={"resource_type": "boat"})).status_code == 422
    assert (await api.patch(url, json={"current_zone_id": str(uuid.uuid4())})).status_code == 422
    assert (await api.patch(url, json={"status": "available"})).status_code == 422   # no change
    assert (await api.patch(f"/api/v1/resources/{uuid.uuid4()}", json={"status": "available"})).status_code == 404


async def test_authorization(api):
    opts = await options(api)
    owner_id = opts["owners"][0]["owner_id"]
    other = other_subject(owner_id, "owner")
    as_owner, as_other = await headers_for_subject(api, owner_id), await headers_for_subject(api, other)
    as_requester = await login_headers(api, REQUESTER_A)

    res = await api.post("/api/v1/resources", json=body(opts, owner_id=None), headers=as_owner)
    assert res.status_code == 201, res.text
    rid = res.json()["resource"]["resource_id"]
    assert res.json()["resource"]["owner_id"] == owner_id

    assert (await api.post("/api/v1/resources", json=body(opts, owner_id=other), headers=as_owner)).status_code == 403
    assert (await api.post("/api/v1/resources", json=body(opts), headers=as_requester)).status_code == 403
    assert (await api.post("/api/v1/resources", json=body(opts), headers={"Authorization": "Bearer junk"})).status_code == 401

    assert (await api.patch(f"/api/v1/resources/{rid}", json={"quantity_total": 12}, headers=as_owner)).status_code == 200
    # Cross-owner: RLS hides the other owner's resource -> 404 for read and update.
    assert (await api.patch(f"/api/v1/resources/{rid}", json={"quantity_total": 20}, headers=as_other)).status_code == 404
    assert (await api.get(f"/api/v1/resources/{rid}", headers=as_other)).status_code == 404
    assert all(r["owner_id"] == other for r in (await api.get("/api/v1/resources", headers=as_other)).json())
    assert [o["owner_id"] for o in (await api.get("/api/v1/resources/form-options", headers=as_other)).json()["owners"]] == [other]
    # Requesters cannot modify (or list with owner details) resources.
    assert (await api.patch(f"/api/v1/resources/{rid}", json={"status": "unavailable"}, headers=as_requester)).status_code == 403
    assert (await api.get("/api/v1/resources", headers=as_requester)).status_code == 403
    assert await scalar("SELECT quantity_total FROM resources WHERE resource_id = :r", r=rid) == 12
