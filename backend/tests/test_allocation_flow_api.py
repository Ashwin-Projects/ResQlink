"""Live API tests: Create Request -> Match -> Reserve -> Allocate -> Confirm -> Fulfilled.

Runs against the REAL database in DATABASE_URL (schema.sql + seed_data.sql) and
is skipped automatically when it is unreachable.

    cd backend
    DATABASE_URL=postgresql+asyncpg://resqlink_app:<APP_DB_PASSWORD>@localhost:5432/resqlink \
    ADMIN_DATABASE_URL=postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink \
        python -m pytest -o asyncio_mode=auto tests/test_allocation_flow_api.py -v
"""
import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from live_support import (COORDINATOR, OWNER_A, admin_engine as engine, headers_for_subject,
                          live_db_available, login_headers)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api():
    err = await live_db_available("SELECT 1 FROM allocations LIMIT 1", "SELECT reservation_id FROM allocations LIMIT 1")
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


async def setup_request(api, qty, rtype="medical_supply"):
    """A real request via the API plus a dedicated resource next to it."""
    opts = (await api.get("/api/v1/requests/form-options")).json()
    zone = opts["zones"][0]
    res = await api.post("/api/v1/requests", json={
        "requester_id": opts["requesters"][0]["requester_id"], "zone_id": zone["zone_id"],
        "resource_type_needed": rtype, "quantity_requested": qty, "urgency_level": "critical",
        "idempotency_key": f"pytest-flow-{uuid.uuid4()}",
    })
    assert res.status_code == 201, res.text
    return res.json(), zone


async def add_resource(zone, qty, rtype="medical_supply"):
    rid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text(f"""
            INSERT INTO resources (resource_id, owner_id, current_zone_id, resource_type, resource_subtype,
                                   quantity_total, quantity_available, unit_of_measure, location, last_verified_at)
            VALUES (:rid, (SELECT owner_id FROM owners ORDER BY name LIMIT 1), :zone, :rtype, 'pytest kit', :q, :q, 'kits',
                    ST_GeogFromText('SRID=4326;POINT({zone['longitude']} {zone['latitude']})'), now())
        """), {"rid": rid, "zone": zone["zone_id"], "rtype": rtype, "q": qty})
    return rid


async def tracking(api, rid):
    res = await api.get(f"/api/v1/requests/{rid}/tracking")
    assert res.status_code == 200, res.text
    return res.json()


async def test_full_flow_pending_matching_partial_fulfilled(api):
    req, zone = await setup_request(api, 50)
    rid = req["request_id"]
    assert req["tracking_stage"] == "pending"
    res_a = await add_resource(zone, 30)

    cands = (await api.get(f"/api/v1/match/requests/{rid}/candidates")).json()
    assert any(c["resource_id"] == str(res_a) for c in cands["candidates"])
    assert cands["quantity_to_cover"] == 50

    m = await api.post(f"/api/v1/match/requests/{rid}/match")
    assert m.status_code == 200, m.text
    reservations = m.json()["proposed_reservations"]
    assert reservations and all("reservation_id" in r for r in reservations)
    t = await tracking(api, rid)
    assert t["stage"] == "matching" and t["quantities"]["reserved"] > 0
    assert t["reservations"][0]["final_score"] is not None

    # Second match must not over-reserve beyond what is still uncovered.
    await api.post(f"/api/v1/match/requests/{rid}/match")
    t = await tracking(api, rid)
    assert t["quantities"]["reserved"] <= 50

    # Allocate every active lease, dispatch and confirm.
    for r in [r for r in t["reservations"] if r["lease_active"]]:
        before = await scalar("SELECT quantity_available FROM resources WHERE resource_id = :r", r=r["resource_id"])
        a = await api.post(f"/api/v1/reservations/{r['reservation_id']}/allocate")
        assert a.status_code == 201, a.text
        alloc = a.json()["allocation"]
        assert alloc["allocation_status"] == "reserved" and alloc["reservation_id"] == r["reservation_id"]
        assert await scalar("SELECT quantity_available FROM resources WHERE resource_id = :r", r=r["resource_id"]) == before
        assert (await api.post(f"/api/v1/allocations/{alloc['allocation_id']}/transition", json={"status": "dispatched"})).status_code == 200
        c = await api.post(f"/api/v1/allocations/{alloc['allocation_id']}/transition", json={"status": "confirmed"})
        assert c.status_code == 200, c.text

    t = await tracking(api, rid)
    fulfilled = t["quantities"]["fulfilled"]
    assert fulfilled > 0
    assert t["stage"] == ("fulfilled" if fulfilled >= 50 else "partially_fulfilled")
    assert await scalar("SELECT quantity_fulfilled FROM emergency_requests WHERE request_id = :r", r=rid) == fulfilled

    if fulfilled < 50:
        await add_resource(zone, 50)
        assert (await api.post(f"/api/v1/match/requests/{rid}/match")).status_code == 200
        t = await tracking(api, rid)
        for r in [r for r in t["reservations"] if r["lease_active"]]:
            alloc = (await api.post(f"/api/v1/reservations/{r['reservation_id']}/allocate")).json()["allocation"]
            await api.post(f"/api/v1/allocations/{alloc['allocation_id']}/transition", json={"status": "dispatched"})
            await api.post(f"/api/v1/allocations/{alloc['allocation_id']}/transition", json={"status": "confirmed"})
        t = await tracking(api, rid)
    assert t["stage"] == "fulfilled" and t["quantities"]["remaining"] == 0
    assert await scalar("SELECT status FROM emergency_requests WHERE request_id = :r", r=rid) == "fulfilled"

    # Audit: reservation, allocation and request rows all present.
    for entity in ("reservation", "allocation"):
        assert await scalar(
            f"SELECT count(*) FROM allocation_history h WHERE h.entity_type = '{entity}' AND "
            "(h.entity_id IN (SELECT reservation_id FROM reservation WHERE request_id = :r) "
            " OR h.allocation_id IN (SELECT allocation_id FROM allocations WHERE request_id = :r))", r=rid) > 0
    assert await scalar("SELECT count(*) FROM allocation_history WHERE entity_type='request' AND entity_id = :r "
                        "AND action = 'status_changed'", r=rid) >= 1


async def test_invalid_allocation_operations(api):
    req, zone = await setup_request(api, 5)
    rid = req["request_id"]
    await add_resource(zone, 5)
    await api.post(f"/api/v1/match/requests/{rid}/match")
    lease = (await tracking(api, rid))["reservations"][0]
    alloc = (await api.post(f"/api/v1/reservations/{lease['reservation_id']}/allocate")).json()["allocation"]
    aid = alloc["allocation_id"]

    assert (await api.post(f"/api/v1/reservations/{lease['reservation_id']}/allocate")).status_code == 409
    skip = await api.post(f"/api/v1/allocations/{aid}/transition", json={"status": "confirmed"})
    assert skip.status_code == 409 and "Invalid allocation status transition" in skip.json()["detail"]
    assert (await api.post(f"/api/v1/allocations/{aid}/transition", json={"status": "fulfilled"})).status_code == 422
    assert (await api.post(f"/api/v1/allocations/{uuid.uuid4()}/transition", json={"status": "dispatched"})).status_code == 404
    assert (await api.post(f"/api/v1/reservations/{uuid.uuid4()}/allocate")).status_code == 404

    await api.post(f"/api/v1/allocations/{aid}/transition", json={"status": "dispatched"})
    await api.post(f"/api/v1/allocations/{aid}/transition", json={"status": "confirmed"})
    assert (await api.post(f"/api/v1/allocations/{aid}/transition", json={"status": "cancelled"})).status_code == 409


async def test_release_returns_quantity(api):
    req, zone = await setup_request(api, 4)
    res_id = await add_resource(zone, 4)
    await api.post(f"/api/v1/match/requests/{req['request_id']}/match")
    lease = next(r for r in (await tracking(api, req["request_id"]))["reservations"] if r["resource_id"] == str(res_id))
    before = await scalar("SELECT quantity_available FROM resources WHERE resource_id = :r", r=res_id)
    rel = await api.post(f"/api/v1/reservations/{lease['reservation_id']}/release")
    assert rel.status_code == 200 and rel.json()["status"] == "cancelled"
    assert await scalar("SELECT quantity_available FROM resources WHERE resource_id = :r", r=res_id) == before + lease["quantity"]
    assert (await api.post(f"/api/v1/reservations/{lease['reservation_id']}/allocate")).status_code == 409


async def test_concurrent_allocation_of_one_lease(api):
    req, zone = await setup_request(api, 6)
    await add_resource(zone, 6)
    await api.post(f"/api/v1/match/requests/{req['request_id']}/match")
    lease = (await tracking(api, req["request_id"]))["reservations"][0]
    url = f"/api/v1/reservations/{lease['reservation_id']}/allocate"
    results = await asyncio.gather(api.post(url), api.post(url), api.post(url))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409], codes
    assert await scalar("SELECT count(*) FROM allocations WHERE reservation_id = :v", v=lease["reservation_id"]) == 1


async def test_only_coordinators_manage_allocations(api):
    req, zone = await setup_request(api, 3)
    await add_resource(zone, 3)
    await api.post(f"/api/v1/match/requests/{req['request_id']}/match")
    lease = (await tracking(api, req["request_id"]))["reservations"][0]
    for headers in (await headers_for_subject(api, req["requester_id"]), await login_headers(api, OWNER_A)):
        res = await api.post(f"/api/v1/reservations/{lease['reservation_id']}/allocate", headers=headers)
        assert res.status_code == 403
        res = await api.post(f"/api/v1/reservations/{lease['reservation_id']}/release", headers=headers)
        assert res.status_code == 403
    assert (await api.post(f"/api/v1/reservations/{lease['reservation_id']}/allocate",
                           headers={"Authorization": "Bearer junk"})).status_code == 401
    t = await tracking(api, req["request_id"])
    assert t["can_manage"] is True and t["viewer_role"] == "coordinator"
