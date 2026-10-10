"""Emergency request intake (POST /api/v1/requests).

Creates an emergency request in ONE PostgreSQL transaction:

  1. INSERT emergency_requests            (status = column default, i.e. 'open')
       -> trg_requests_log_insert writes the immutable allocation_history
          'request/created' audit row (migration 0010)
  2. UPSERT pool (zone x resource_type x mobility_class)
  3. INSERT request_pool_dependency       (registers the request in the
                                           pool-dependency index used by
                                           MatchingEngine.incremental_rematch)
  4. INSERT event_outbox 'request_created' (transactional outbox, carries pool_id)

The session arrives with the caller's RLS role already set by
app.api.deps.get_db_with_rls (SET LOCAL ROLE api_<role>), so every statement
here is subject to the database's own grants and row-level-security policies.
"""
import json
import logging
import uuid
from typing import Optional, Tuple

from fastapi import HTTPException, status
from geoalchemy2 import WKTElement
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from shapely.wkt import loads as wkt_loads
from sqlalchemy import select, text, exc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import EmergencyRequest, Requester, Zone
from app.schemas.schemas import EmergencyRequestCreate, TokenData

logger = logging.getLogger(__name__)

# Single source for the request read-model (list + create responses).
REQUEST_SELECT_SQL = """
    SELECT r.request_id, r.requester_id, r.zone_id, z.zone_name,
           r.resource_type_needed, r.quantity_requested, r.quantity_fulfilled,
           r.urgency_level, r.status, r.description, r.needed_by,
           r.idempotency_key, r.source_channel,
           r.requested_at, r.created_at, r.updated_at,
           ST_Y(r.location::geometry) AS latitude,
           ST_X(r.location::geometry) AS longitude
    FROM emergency_requests r
    JOIN zones z ON z.zone_id = r.zone_id
"""

POOL_DEPENDENCY_SQL = text("""
    SELECT p.pool_id, p.zone_id, p.resource_type, p.mobility_class
    FROM request_pool_dependency d
    JOIN pool p ON p.pool_id = d.pool_id
    WHERE d.request_id = :request_id
    ORDER BY d.created_at
    LIMIT 1
""")


def _pg_code(error: exc.DBAPIError) -> Optional[str]:
    """SQLSTATE of a driver error (asyncpg exposes .sqlstate, psycopg .pgcode)."""
    orig = getattr(error, "orig", None)
    for candidate in (orig, getattr(orig, "__cause__", None)):
        for attr in ("pgcode", "sqlstate"):
            code = getattr(candidate, attr, None)
            if code:
                return code
    return None


def _row_to_dict(row) -> dict:
    data = dict(row)
    for key in ("quantity_requested", "quantity_fulfilled"):
        if data.get(key) is not None:
            data[key] = float(data[key])
    return data


async def fetch_request(db: AsyncSession, request_id: uuid.UUID) -> Optional[dict]:
    row = (await db.execute(text(REQUEST_SELECT_SQL + " WHERE r.request_id = :rid"), {"rid": request_id})).mappings().first()
    return _row_to_dict(row) if row else None


async def list_requests(db: AsyncSession, skip: int, limit: int) -> list:
    stmt = text(REQUEST_SELECT_SQL + " ORDER BY r.created_at DESC, r.request_id OFFSET :skip LIMIT :limit")
    rows = (await db.execute(stmt, {"skip": skip, "limit": limit})).mappings().all()
    return [_row_to_dict(r) for r in rows]


async def _fetch_pool_dependency(db: AsyncSession, request_id: uuid.UUID) -> Optional[dict]:
    row = (await db.execute(POOL_DEPENDENCY_SQL, {"request_id": request_id})).mappings().first()
    return dict(row) if row else None


def _authorize(current_user: TokenData, payload: EmergencyRequestCreate) -> None:
    """Application-level mirror of the database permissions (migrations 0009/0010).

    The database remains the enforcement point (owner role has no INSERT grant
    on emergency_requests; requester RLS policy only admits its own
    requester_id); these checks just return a clear 403 instead of a raw
    database error.
    """
    if current_user.role == "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Resource owners are not permitted to create emergency requests.")
    if current_user.role == "requester" and str(payload.requester_id) != str(current_user.sub):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requesters can only create emergency requests for themselves.")


def _location_value(payload: EmergencyRequestCreate):
    """Returns the value to store in emergency_requests.location."""
    if payload.latitude is not None and payload.longitude is not None:
        return WKTElement(f"POINT({payload.longitude} {payload.latitude})", srid=4326)
    if payload.location_wkt:
        try:
            geom = wkt_loads(payload.location_wkt)
        except Exception:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "location_wkt is not valid WKT.")
        if not isinstance(geom, Point) or geom.is_empty:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "location_wkt must be a POINT.")
        if not (-180 <= geom.x <= 180 and -90 <= geom.y <= 90):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "location_wkt coordinates are out of range.")
        return from_shape(geom, srid=4326)
    # Default: the selected zone's own point (zones.location).
    return select(Zone.location).where(Zone.zone_id == payload.zone_id).scalar_subquery()


async def _idempotent_replay(db: AsyncSession, key: str, current_user: TokenData) -> Optional[Tuple[dict, Optional[dict]]]:
    existing_id = (await db.execute(
        select(EmergencyRequest.request_id).where(EmergencyRequest.idempotency_key == key)
    )).scalar_one_or_none()
    if existing_id is None:
        return None
    request = await fetch_request(db, existing_id)
    if request is None:
        return None
    if current_user.role == "requester" and str(request["requester_id"]) != str(current_user.sub):
        raise HTTPException(status.HTTP_409_CONFLICT, "idempotency_key is already in use.")
    return request, await _fetch_pool_dependency(db, existing_id)


async def create_emergency_request(
    db: AsyncSession, payload: EmergencyRequestCreate, current_user: TokenData
) -> Tuple[dict, Optional[dict], Optional[uuid.UUID], bool]:
    """Returns (request, pool_dependency, event_outbox_id, idempotent_replay)."""
    _authorize(current_user, payload)

    try:
        if payload.idempotency_key:
            replay = await _idempotent_replay(db, payload.idempotency_key, current_user)
            if replay:
                await db.commit()
                return replay[0], replay[1], None, True

        # Referential checks with clear messages (the FKs still enforce them).
        requester_exists = (await db.execute(
            select(Requester.requester_id).where(Requester.requester_id == payload.requester_id)
        )).scalar_one_or_none()
        if requester_exists is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown requester_id: no such requester.")
        zone_exists = (await db.execute(
            select(Zone.zone_id).where(Zone.zone_id == payload.zone_id)
        )).scalar_one_or_none()
        if zone_exists is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown zone_id: no such zone.")

        # 1. The request itself. `status` is omitted so the column default
        #    (the database-defined initial lifecycle state) applies.
        request_obj = EmergencyRequest(
            requester_id=payload.requester_id,
            zone_id=payload.zone_id,
            resource_type_needed=payload.resource_type_needed,
            quantity_requested=payload.quantity_requested,
            urgency_level=payload.urgency_level,
            description=payload.description,
            needed_by=payload.needed_by,
            idempotency_key=payload.idempotency_key,
            source_channel=payload.source_channel,
            location=_location_value(payload),
        )
        db.add(request_obj)
        await db.flush()
        request_id = request_obj.request_id

        # 2. Pool (zone x resource_type x mobility_class) — upsert.
        pool_params = {
            "zone_id": payload.zone_id,
            "resource_type": payload.resource_type_needed,
            "mobility_class": payload.mobility_requirement,
        }
        await db.execute(text("""
            INSERT INTO pool (zone_id, resource_type, mobility_class)
            VALUES (:zone_id, :resource_type, :mobility_class)
            ON CONFLICT ON CONSTRAINT uq_pool_zone_type_mob DO NOTHING
        """), pool_params)
        pool_id = (await db.execute(text("""
            SELECT pool_id FROM pool
            WHERE zone_id = :zone_id AND resource_type = :resource_type AND mobility_class = :mobility_class
        """), pool_params)).scalar_one()

        # 3. Register the request in the pool-dependency index.
        await db.execute(text("""
            INSERT INTO request_pool_dependency (request_id, pool_id) VALUES (:request_id, :pool_id)
        """), {"request_id": request_id, "pool_id": pool_id})

        # 4. Transactional outbox event (same transaction as the state change).
        event_id = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO event_outbox (event_id, event_type, pool_id, payload)
            VALUES (:event_id, 'request_created', :pool_id, CAST(:payload AS jsonb))
        """), {
            "event_id": event_id,
            "pool_id": pool_id,
            "payload": json.dumps({
                "request_id": str(request_id),
                "zone_id": str(payload.zone_id),
                "resource_type_needed": payload.resource_type_needed,
                "urgency": payload.urgency_level,
                "quantity_requested": float(payload.quantity_requested),
                "mobility_requirement": payload.mobility_requirement,
            }),
        })

        # Read back the database's view of the row (defaults, timestamps,
        # stored location) inside the same RLS-scoped transaction.
        created = await fetch_request(db, request_id)
        pool_dependency = {"pool_id": pool_id, **pool_params}
        await db.commit()
        return created, pool_dependency, event_id, False

    except HTTPException:
        await db.rollback()
        raise
    except exc.DBAPIError as e:
        await db.rollback()
        code = _pg_code(e)
        if code == "23505" and payload.idempotency_key:
            # Concurrent submission with the same idempotency key won the race.
            replay = await _idempotent_replay(db, payload.idempotency_key, current_user)
            await db.commit()
            if replay:
                return replay[0], replay[1], None, True
        if code == "42501":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not permitted to create this emergency request.")
        if code == "23503":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Referenced requester or zone does not exist.")
        if code in ("23514", "23502", "22003", "22P02"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Request violates a database constraint.")
        if code == "23505":
            raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate emergency request.")
        logger.exception("Emergency request creation failed (SQLSTATE %s)", code)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error while creating the emergency request.")
