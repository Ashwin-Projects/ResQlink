"""End-to-end API tests for Create Emergency Request (POST /api/v1/requests).

These run against the REAL database configured by DATABASE_URL (e.g. the
docker-compose PostGIS service initialised from schema.sql + seed_data.sql).
They are skipped automatically if that database is unreachable, so they never
pass against mock data. Callers log in with the seeded demo accounts through
POST /api/v1/auth/login (see tests/live_support.py).

    cd backend
    DATABASE_URL=postgresql+asyncpg://resqlink_app:<APP_DB_PASSWORD>@localhost:5432/resqlink \
    ADMIN_DATABASE_URL=postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink \
        python -m pytest tests/test_request_creation.py -v
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


async def db_scalar(sql, **params):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def _options(api):
    res = await api.get("/api/v1/requests/form-options")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["requesters"] and data["zones"], "seed data (requesters/zones) required"
    return data


def _payload(opts, **overrides):
    body = {
        "requester_id": opts["requesters"][0]["requester_id"],
        "zone_id": opts["zones"][0]["zone_id"],
        "resource_type_needed": "medical_supply",
        "quantity_requested": 50,
        "urgency_level": "critical",
        "mobility_requirement": "boat",
        "description": "Medical supplies required for flooded shelter",
        "source_channel": "pytest",
        "idempotency_key": f"pytest-{uuid.uuid4()}",
    }
    body.update(overrides)
    return body


async def test_form_options_from_database(api):
    data = await _options(api)
    assert "critical" in data["urgency_levels"]
    assert "medical_supply" in data["resource_types"]
    assert data["current_role"] == "coordinator"


async def test_create_request_persists_with_dependency_outbox_and_audit(api):
    opts = await _options(api)
    res = await api.post("/api/v1/requests", json=_payload(opts))
    assert res.status_code == 201, res.text
    body = res.json()
    rid = body["request_id"]
    assert body["status"] == "open"  # database column default
    assert body["quantity_requested"] == 50
    assert body["urgency_level"] == "critical"
    assert body["zone_name"] == opts["zones"][0]["zone_name"]
    assert body["pool_dependency"]["mobility_class"] == "boat"
    assert body["idempotent_replay"] is False

    assert await db_scalar("SELECT status FROM emergency_requests WHERE request_id = :r", r=rid) == "open"
    assert await db_scalar("SELECT count(*) FROM request_pool_dependency WHERE request_id = :r", r=rid) == 1
    assert await db_scalar(
        "SELECT count(*) FROM event_outbox WHERE event_id = :e AND event_type = 'request_created' AND pool_id IS NOT NULL",
        e=body["event_outbox_id"]) == 1
    assert await db_scalar(
        "SELECT count(*) FROM allocation_history WHERE entity_type = 'request' AND entity_id = :r AND action = 'created'", r=rid) == 1

    listed = await api.get("/api/v1/requests?limit=50")
    assert listed.status_code == 200
    assert rid in [r["request_id"] for r in listed.json()]

    history = await api.get(f"/api/v1/audit/requests/{rid}/history")
    assert history.status_code == 200 and len(history.json()["history"]) == 1


async def test_request_is_visible_to_incremental_rematch(api):
    opts = await _options(api)
    body = (await api.post("/api/v1/requests", json=_payload(opts))).json()
    res = await api.post(f"/api/v1/match/engine/incremental/{body['pool_dependency']['pool_id']}")
    assert res.status_code == 200, res.text
    assert res.json()["stats"]["requests_examined"] >= 1


async def test_idempotent_replay_returns_same_request(api):
    opts = await _options(api)
    payload = _payload(opts)
    first = await api.post("/api/v1/requests", json=payload)
    second = await api.post("/api/v1/requests", json=payload)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["request_id"] == first.json()["request_id"]
    assert second.json()["idempotent_replay"] is True
    assert await db_scalar("SELECT count(*) FROM emergency_requests WHERE idempotency_key = :k",
                           k=payload["idempotency_key"]) == 1


async def test_explicit_coordinates_are_stored(api):
    opts = await _options(api)
    res = await api.post("/api/v1/requests", json=_payload(opts, latitude=13.0827, longitude=80.2707))
    assert res.status_code == 201, res.text
    assert abs(res.json()["latitude"] - 13.0827) < 1e-6 and abs(res.json()["longitude"] - 80.2707) < 1e-6


@pytest.mark.parametrize("override,missing", [
    ({"quantity_requested": 0}, None),
    ({"quantity_requested": -1}, None),
    ({"quantity_requested": "1.234"}, None),
    ({"urgency_level": "extreme"}, None),
    ({"resource_type_needed": "spaceship"}, None),
    ({"status": "fulfilled"}, None),
    ({}, "requester_id"),
    ({}, "zone_id"),
    ({}, "quantity_requested"),
    ({}, "urgency_level"),
])
async def test_invalid_payloads_rejected_and_not_persisted(api, override, missing):
    opts = await _options(api)
    payload = _payload(opts, **override)
    if missing:
        payload.pop(missing)
    before = await db_scalar("SELECT count(*) FROM emergency_requests")
    res = await api.post("/api/v1/requests", json=payload)
    assert res.status_code == 422, res.text
    assert await db_scalar("SELECT count(*) FROM emergency_requests") == before


async def test_unknown_zone_and_requester(api):
    opts = await _options(api)
    res = await api.post("/api/v1/requests", json=_payload(opts, zone_id=str(uuid.uuid4())))
    assert res.status_code == 422 and "zone" in res.json()["detail"].lower()
    res = await api.post("/api/v1/requests", json=_payload(opts, requester_id=str(uuid.uuid4())))
    assert res.status_code == 422 and "requester" in res.json()["detail"].lower()


async def test_authorization_rules(api):
    opts = await _options(api)
    requester_id = opts["requesters"][0]["requester_id"]
    as_requester = await headers_for_subject(api, requester_id)

    res = await api.post("/api/v1/requests", json=_payload(opts), headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401

    res = await api.post("/api/v1/requests", json=_payload(opts), headers=await login_headers(api, OWNER_A))
    assert res.status_code == 403

    # Requester creating its own request: allowed by RLS + migration 0010 grants.
    res = await api.post("/api/v1/requests", json=_payload(opts), headers=as_requester)
    assert res.status_code == 201, res.text

    # ... but never on behalf of another requester (API 403; RLS WITH CHECK would also refuse).
    res = await api.post("/api/v1/requests", json=_payload(opts, requester_id=other_subject(requester_id, "requester")),
                         headers=as_requester)
    assert res.status_code == 403

    # A requester's form options only contain itself (RLS on requesters).
    mine = (await api.get("/api/v1/requests/form-options", headers=as_requester)).json()
    assert [r["requester_id"] for r in mine["requesters"]] == [requester_id]
    # ... and its request list only its own requests.
    listed = (await api.get("/api/v1/requests?limit=500", headers=as_requester)).json()
    assert listed and all(r["requester_id"] == requester_id for r in listed)


async def test_requester_cannot_match_or_read_audit(api):
    opts = await _options(api)
    body = (await api.post("/api/v1/requests", json=_payload(opts))).json()
    as_requester = await headers_for_subject(api, body["requester_id"])
    assert (await api.post(f"/api/v1/match/requests/{body['request_id']}/match", headers=as_requester)).status_code == 403
    assert (await api.get(f"/api/v1/audit/requests/{body['request_id']}/history", headers=as_requester)).status_code == 403
