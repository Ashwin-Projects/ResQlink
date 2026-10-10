"""Live API tests for Request Status Tracking (GET /api/v1/requests/{id}/tracking).

Run against the REAL database in DATABASE_URL (schema.sql + seed_data.sql);
skipped automatically when it is unreachable.

    cd backend
    DATABASE_URL=postgresql+asyncpg://resqlink_app:<APP_DB_PASSWORD>@localhost:5432/resqlink \
    ADMIN_DATABASE_URL=postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink \
        python -m pytest -o asyncio_mode=auto tests/test_request_tracking_api.py -v
"""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from live_support import (COORDINATOR, OWNER_A, admin_engine as engine, headers_for_subject,
                          live_db_available, login_headers, other_subject)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api():
    err = await live_db_available("SELECT 1 FROM emergency_requests LIMIT 1")
    if err is not None:  # pragma: no cover - environment dependent
        pytest.skip(f"Live PostgreSQL not available: {err}")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Default caller: the seeded coordinator, logged in through POST /api/v1/auth/login.
        client.headers.update(await login_headers(client, COORDINATOR))
        yield client
    await engine.dispose()


async def sql(statement, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(statement), params))


async def _new_request(api, qty=50, rtype="medical_supply"):
    opts = (await api.get("/api/v1/requests/form-options")).json()
    zone = opts["zones"][0]
    body = {
        "requester_id": opts["requesters"][0]["requester_id"], "zone_id": zone["zone_id"],
        "resource_type_needed": rtype, "quantity_requested": qty, "urgency_level": "critical",
        "description": "tracking test", "idempotency_key": f"pytest-track-{uuid.uuid4()}",
    }
    res = await api.post("/api/v1/requests", json=body)
    assert res.status_code == 201, res.text
    return res.json(), zone


async def _new_resource(zone, rtype, qty):
    rid = uuid.uuid4()
    await sql(f"""
        INSERT INTO resources (resource_id, owner_id, current_zone_id, resource_type, resource_subtype,
                               quantity_total, quantity_available, unit_of_measure, location, last_verified_at)
        VALUES (:rid, (SELECT owner_id FROM owners ORDER BY name LIMIT 1), :zone, :rtype, 'pytest kit',
                :qty, :qty, 'kits', ST_GeogFromText('SRID=4326;POINT({zone['longitude']} {zone['latitude']})'), now())
    """, rid=rid, zone=zone["zone_id"], rtype=rtype, qty=qty)
    return rid


async def _tracking(api, request_id, **kw):
    res = await api.get(f"/api/v1/requests/{request_id}/tracking", **kw)
    return res


async def test_new_request_is_pending(api):
    created, _ = await _new_request(api)
    assert created["tracking_stage"] == "pending" and created["quantity_remaining"] == 50
    res = await _tracking(api, created["request_id"])
    assert res.status_code == 200, res.text
    t = res.json()
    assert t["db_status"] == "open" and t["stage"] == "pending" and not t["is_terminal"]
    assert [s["state"] for s in t["steps"]] == ["current", "upcoming", "upcoming", "upcoming"]
    assert t["quantities"] == {"requested": 50, "fulfilled": 0, "remaining": 50, "reserved": 0, "in_progress": 0}
    assert t["timeline"][0]["kind"] == "request_created"


async def test_full_lifecycle_pending_matching_partial_fulfilled(api):
    created, zone = await _new_request(api, qty=50)
    rid = created["request_id"]
    res1 = await _new_resource(zone, "medical_supply", 30)

    # Matching: the real matching engine leases a reservation (FOR UPDATE SKIP LOCKED).
    m = await api.post(f"/api/v1/match/requests/{rid}/match")
    assert m.status_code == 200, m.text
    t = (await _tracking(api, rid)).json()
    assert t["stage"] == "matching" and t["db_status"] == "open"
    assert t["quantities"]["reserved"] > 0 and t["reservations"] and t["reservations"][0]["lease_active"]

    # Allocations driven through the existing DB state machine.
    alloc = uuid.uuid4()
    await sql("UPDATE reservation SET status = 'expired' WHERE request_id = :r", r=rid)  # release the lease(s)
    await sql("INSERT INTO allocations (allocation_id, request_id, resource_id, quantity_allocated) VALUES (:a, :r, :res, 30)",
              a=alloc, r=rid, res=res1)
    for st in ("dispatched", "in_transit", "delivered", "confirmed"):
        await sql("UPDATE allocations SET allocation_status = :s WHERE allocation_id = :a", s=st, a=alloc)
    t = (await _tracking(api, rid)).json()
    assert t["db_status"] == "partially_fulfilled" and t["stage"] == "partially_fulfilled"
    assert t["quantities"]["fulfilled"] == 30 and t["quantities"]["remaining"] == 20
    assert t["allocations"][0]["confirmed_at"] is not None
    assert any("open → partially_fulfilled" in e["label"] for e in t["timeline"])

    res2 = await _new_resource(zone, "medical_supply", 20)
    alloc2 = uuid.uuid4()
    await sql("INSERT INTO allocations (allocation_id, request_id, resource_id, quantity_allocated) VALUES (:a, :r, :res, 20)",
              a=alloc2, r=rid, res=res2)
    for st in ("dispatched", "in_transit", "delivered", "confirmed"):
        await sql("UPDATE allocations SET allocation_status = :s WHERE allocation_id = :a", s=st, a=alloc2)
    t = (await _tracking(api, rid)).json()
    assert t["stage"] == "fulfilled" and t["is_terminal"] and t["quantities"]["remaining"] == 0
    assert all(s["state"] == "complete" for s in t["steps"])

    listed = {r["request_id"]: r for r in (await api.get("/api/v1/requests?limit=500")).json()}
    assert listed[rid]["tracking_stage"] == "fulfilled"


async def test_invalid_transitions_rejected_by_database(api):
    created, _ = await _new_request(api, qty=5)
    rid = created["request_id"]
    with pytest.raises(Exception, match="emergency_requests_status_check"):
        await sql("INSERT INTO emergency_requests (requester_id, zone_id, resource_type_needed, quantity_requested, urgency_level, status, location) "
                  "SELECT requester_id, zone_id, 'boat', 1, 'low', 'matching', location FROM emergency_requests WHERE request_id = :r", r=rid)
    await sql("UPDATE emergency_requests SET status = 'cancelled' WHERE request_id = :r", r=rid)
    with pytest.raises(Exception, match="Invalid emergency request status transition"):
        await sql("UPDATE emergency_requests SET status = 'open' WHERE request_id = :r", r=rid)
    t = (await _tracking(api, rid)).json()
    assert t["stage"] == "cancelled" and t["is_terminal"]
    assert [s["state"] for s in t["steps"]][2:] == ["skipped", "skipped"]


async def test_not_found_and_validation(api):
    assert (await _tracking(api, uuid.uuid4())).status_code == 404
    assert (await api.get("/api/v1/requests/not-a-uuid/tracking")).status_code == 422


async def test_tracking_respects_roles(api):
    created, _ = await _new_request(api)
    rid = created["request_id"]
    # Owner role has no SELECT on emergency_requests (API 403 before the DB would refuse too).
    assert (await _tracking(api, rid, headers=await login_headers(api, OWNER_A))).status_code == 403
    # A requester only sees its own requests (RLS) -> someone else's request is "not found".
    other = other_subject(created["requester_id"], "requester")
    assert (await _tracking(api, rid, headers=await headers_for_subject(api, other))).status_code == 404
    assert (await _tracking(api, rid, headers=await headers_for_subject(api, created["requester_id"]))).status_code == 200
    assert (await _tracking(api, rid, headers={"Authorization": "Bearer junk"})).status_code == 401
