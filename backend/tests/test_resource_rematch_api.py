"""Live tests: resource change -> event_outbox -> affected pools -> request_pool_dependency
-> incremental re-matching of ONLY the dependent requests (real MatchingEngine, PostGIS).

Runs against the REAL database in DATABASE_URL (schema.sql incl. migration 0014 + seed_data.sql);
skipped automatically when it is unreachable.

    cd backend
    DATABASE_URL=postgresql+asyncpg://resqlink_app:<APP_DB_PASSWORD>@localhost:5432/resqlink \
    ADMIN_DATABASE_URL=postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink \
        python -m pytest -o asyncio_mode=auto tests/test_resource_rematch_api.py -v
"""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.db.session import service_session
from live_support import (COORDINATOR, OWNER_A, REQUESTER_A, admin_engine as engine, live_db_available, login_headers)
from app.services import rematch

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api():
    err = await live_db_available("SELECT processing_result FROM event_outbox LIMIT 1", "SELECT 'fn_lock_resource_leases'::regproc")
    if err is not None:  # pragma: no cover - environment dependent
        pytest.skip(f"Live PostgreSQL not available: {err}")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Default caller: the seeded coordinator, logged in through POST /api/v1/auth/login.
        client.headers.update(await login_headers(client, COORDINATOR))
        yield client
    await engine.dispose()


async def scalar(sql, **p):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), p)).scalar()


async def rows(sql, **p):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), p)).mappings().all()


async def opts(api):
    o = (await api.get("/api/v1/resources/form-options")).json()
    r = (await api.get("/api/v1/requests/form-options")).json()
    return o, r


async def new_resource(api, o, zone, rtype, qty):
    res = await api.post("/api/v1/resources", json={
        "owner_id": o["owners"][0]["owner_id"], "current_zone_id": zone["zone_id"], "resource_type": rtype,
        "quantity_total": qty, "unit_of_measure": "units", "resource_subtype": "pytest rematch",
        "latitude": zone["latitude"], "longitude": zone["longitude"]})
    assert res.status_code == 201, res.text
    return res.json()


async def new_request(api, r, zone, rtype, qty):
    res = await api.post("/api/v1/requests", json={
        "requester_id": r["requesters"][0]["requester_id"], "zone_id": zone["zone_id"], "resource_type_needed": rtype,
        "quantity_requested": qty, "urgency_level": "critical", "idempotency_key": f"pytest-rm-{uuid.uuid4()}"})
    assert res.status_code == 201, res.text
    return res.json()["request_id"]


async def active_leases(request_id):
    return {str(x["resource_id"]): float(x["q"]) for x in await rows(
        "SELECT resource_id, sum(quantity) AS q FROM reservation WHERE request_id = :r AND status = 'active' GROUP BY resource_id", r=request_id)}


async def test_unavailable_resource_rematches_only_dependents(api):
    o, r = await opts(api)
    zone = o["zones"][0]
    res = (await new_resource(api, o, zone, "medical_supply", 12))["resource"]
    rid = res["resource_id"]
    dep = await new_request(api, r, zone, "medical_supply", 12)            # dependent of (zone, medical_supply)
    unrelated = await new_request(api, r, zone, "shelter_capacity", 1)     # same zone, other type
    for x in (dep, unrelated):
        assert (await api.post(f"/api/v1/match/requests/{x}/match")).status_code == 200
    assert (await active_leases(dep)).get(rid, 0) > 0
    unrelated_before = (await active_leases(unrelated),
                        await scalar("SELECT count(*) FROM matching_decision WHERE request_id = :r", r=unrelated))

    out = await api.patch(f"/api/v1/resources/{rid}", json={"status": "unavailable"})
    assert out.status_code == 200, out.text
    body = out.json()
    rm = body["rematch"]
    assert body["before"]["status"] in ("available", "depleted") and body["after"]["status"] == "unavailable"
    assert any(x["request_id"] == dep for x in body["revoked_leases"])
    assert rm["status"] == "processed"
    assert all(p["resource_type"] == "medical_supply" and p["zone_id"] == zone["zone_id"] for p in rm["affected_pools"])
    assert dep in rm["affected_request_ids"] and unrelated not in rm["affected_request_ids"]

    # Every affected request is a dependent of an affected pool or lost a lease.
    pool_ids = [p["pool_id"] for p in rm["affected_pools"]]
    deps = {str(x["request_id"]) for x in await rows(
        "SELECT request_id FROM request_pool_dependency WHERE pool_id = ANY(CAST(:p AS uuid[]))", p=pool_ids)}
    revoked = {x["request_id"] for x in body["revoked_leases"]}
    assert set(rm["affected_request_ids"]) == deps | revoked

    # No lease left on the unavailable resource; unrelated request untouched.
    assert await scalar("SELECT count(*) FROM reservation WHERE resource_id = :r AND status = 'active'", r=rid) == 0
    assert (await active_leases(unrelated),
            await scalar("SELECT count(*) FROM matching_decision WHERE request_id = :r", r=unrelated)) == unrelated_before

    # Event + audit records.
    ev = (await rows("SELECT event_type, processed_at, processing_result FROM event_outbox WHERE event_id = :e",
                     e=body["event_outbox_id"]))[0]
    assert ev["event_type"] == "resource_updated" and ev["processed_at"] is not None and ev["processing_result"]["status"] == "processed"
    assert await scalar("SELECT count(*) FROM allocation_history WHERE entity_type = 'reservation' AND action = 'status_changed' "
                        "AND entity_id IN (SELECT reservation_id FROM reservation WHERE resource_id = :r AND status = 'cancelled')", r=rid) >= 1
    assert await scalar("SELECT action FROM allocation_history WHERE entity_type = 'resource' AND entity_id = :r "
                        "ORDER BY performed_at DESC LIMIT 1", r=rid) == "status_changed"

    # Consistency: request never over-committed; resource quantities add up.
    assert await scalar("""SELECT quantity_fulfilled + COALESCE((SELECT sum(quantity) FROM reservation WHERE request_id = :r AND status='active'),0)
                           <= quantity_requested FROM emergency_requests WHERE request_id = :r""", r=dep)
    assert await scalar("SELECT quantity_available = quantity_total FROM resources WHERE resource_id = :r", r=rid)

    # The stored result is what the runs endpoint returns.
    runs = (await api.get("/api/v1/hazards/rematch-runs?limit=5")).json()
    assert any(x["event_id"] == body["event_outbox_id"] for x in runs)


async def test_stock_cut_revokes_only_needed_leases(api):
    o, r = await opts(api)
    zone = o["zones"][0]
    rid = (await new_resource(api, o, zone, "volunteer", 10))["resource"]["resource_id"]
    a = await new_request(api, r, zone, "volunteer", 6)
    b = await new_request(api, r, zone, "volunteer", 4)
    for x in (a, b):
        await api.post(f"/api/v1/match/requests/{x}/match")
    leased = await scalar("SELECT COALESCE(sum(quantity),0) FROM reservation WHERE resource_id = :r AND status='active'", r=rid)
    out = (await api.patch(f"/api/v1/resources/{rid}", json={"quantity_total": 6})).json()
    freed = sum(x["quantity"] for x in out["revoked_leases"])
    assert freed >= float(leased) - 6
    assert out["resource"]["quantity_total"] == 6 and out["resource"]["quantity_available"] >= 0
    assert set(x["request_id"] for x in out["revoked_leases"]) <= set(out["rematch"]["affected_request_ids"])


async def test_allocated_quantity_is_never_revoked(api):
    o, r = await opts(api)
    zone = o["zones"][0]
    rid = (await new_resource(api, o, zone, "vehicle", 4))["resource"]["resource_id"]
    req = await new_request(api, r, zone, "vehicle", 4)
    await api.post(f"/api/v1/match/requests/{req}/match")
    lease = (await rows("SELECT reservation_id FROM reservation WHERE request_id = :r AND resource_id = :s AND status='active'", r=req, s=rid))[0]
    assert (await api.post(f"/api/v1/reservations/{lease['reservation_id']}/allocate")).status_code == 201
    res = await api.patch(f"/api/v1/resources/{rid}", json={"quantity_total": 1})
    assert res.status_code == 409 and "allocated" in res.json()["detail"]


async def test_notes_only_change_skips_rematch(api):
    o, _ = await opts(api)
    rid = (await new_resource(api, o, o["zones"][0], "other", 2))["resource"]["resource_id"]
    out = (await api.patch(f"/api/v1/resources/{rid}", json={"condition_notes": "label replaced"})).json()
    assert out["rematch"]["status"] == "skipped"


async def test_event_processed_exactly_once(api):
    o, _ = await opts(api)
    rid = (await new_resource(api, o, o["zones"][0], "other", 3))["resource"]["resource_id"]
    out = (await api.patch(f"/api/v1/resources/{rid}", json={"status": "maintenance"})).json()
    again = await rematch.process_event_now(service_session, out["event_outbox_id"])
    assert again["status"] == "already_processed"


async def test_requester_cannot_change_resources_or_read_runs(api):
    o, _ = await opts(api)
    rid = (await new_resource(api, o, o["zones"][0], "other", 1))["resource"]["resource_id"]
    tok = await login_headers(api, REQUESTER_A)
    assert (await api.patch(f"/api/v1/resources/{rid}", json={"status": "unavailable"}, headers=tok)).status_code == 403
    assert (await api.get("/api/v1/hazards/rematch-runs", headers=tok)).status_code == 403


async def test_owner_cannot_read_rematch_runs_or_trigger_hazards(api):
    as_owner = await login_headers(api, OWNER_A)
    assert (await api.get("/api/v1/hazards/rematch-runs", headers=as_owner)).status_code == 403
    assert (await api.post("/api/v1/hazards/trigger-event", json={"pool_id": str(uuid.uuid4())}, headers=as_owner)).status_code == 403
