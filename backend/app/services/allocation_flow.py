"""Reservation -> Allocation workflow (coordinator actions).

    Match (existing MatchingEngine.match_request)
        -> reservation 'active' (leased; trigger decrements resources.quantity_available)
    Allocate  POST /api/v1/reservations/{id}/allocate
        -> reservation 'completed' (quantity stays consumed)
        -> allocation  'reserved'  (not decremented again; linked via allocations.reservation_id, UNIQUE)
    Dispatch / deliver / confirm  POST /api/v1/allocations/{id}/transition
        -> existing allocation state machine (fn_allocations_on_status_change)
        -> on 'confirmed' the database rolls quantity_fulfilled / request status up
    Release   POST /api/v1/reservations/{id}/release
        -> reservation 'cancelled' (trigger releases the quantity)

Every step runs in ONE transaction with explicit row locks, writes a
transactional outbox event, and is audited by database triggers
(allocation_history: reservation / allocation / request rows).
"""
import json
import logging
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import text, exc
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.request_intake import _pg_code

logger = logging.getLogger(__name__)

IN_FLIGHT = ("pending", "matched", "proposed", "reserved", "dispatched", "in_transit", "delivered")
# Targets a coordinator may request through the API. The database state
# machine still decides whether the transition from the CURRENT state is legal.
API_TARGETS = ("dispatched", "in_transit", "delivered", "confirmed", "cancelled")
# The DB state machine lets 'cancelled' through from any state (including
# confirmed). The API only allows cancelling allocations that have not been
# delivered/confirmed, so fulfilled quantity can never be released twice.
CANCELLABLE_FROM = ("pending", "matched", "proposed", "reserved", "dispatched", "in_transit")

LOCK_RESERVATION_SQL = text("""
    SELECT reservation_id, request_id, resource_id, quantity, status, lease_expires_at,
           priority_snapshot, (lease_expires_at > now()) AS lease_valid
    FROM reservation WHERE reservation_id = :reservation_id
    FOR UPDATE
""")

LOCK_REQUEST_SQL = text("""
    SELECT request_id, status, quantity_requested, quantity_fulfilled
    FROM emergency_requests WHERE request_id = :request_id
    FOR UPDATE
""")

IN_FLIGHT_QTY_SQL = text("""
    SELECT COALESCE(sum(quantity_allocated), 0) FROM allocations
    WHERE request_id = :request_id AND allocation_status = ANY(CAST(:in_flight AS text[]))
""")

COMPLETE_RESERVATION_SQL = text("""
    UPDATE reservation SET status = 'completed' WHERE reservation_id = :reservation_id AND status = 'active'
""")

INSERT_ALLOCATION_SQL = text("""
    INSERT INTO allocations (allocation_id, request_id, resource_id, reservation_id, matched_by,
                             quantity_allocated, allocation_status, distance_km, priority_score, notes)
    SELECT :allocation_id, v.request_id, v.resource_id, v.reservation_id,
           (SELECT u.user_id FROM system_users u WHERE u.user_id = CAST(:actor AS uuid)),
           v.quantity, 'reserved',
           round((ST_Distance(res.location, r.location) / 1000.0)::numeric, 2),
           v.priority_snapshot,
           :notes
    FROM reservation v
    JOIN resources res ON res.resource_id = v.resource_id
    JOIN emergency_requests r ON r.request_id = v.request_id
    WHERE v.reservation_id = :reservation_id
""")

RELEASE_RESERVATION_SQL = text("""
    UPDATE reservation SET status = 'cancelled' WHERE reservation_id = :reservation_id AND status = 'active'
""")

LOCK_ALLOCATION_SQL = text("""
    SELECT allocation_id, request_id, resource_id, quantity_allocated, allocation_status
    FROM allocations WHERE allocation_id = :allocation_id
    FOR UPDATE
""")

UPDATE_ALLOCATION_SQL = text("""
    UPDATE allocations
    SET allocation_status = :target,
        notes = COALESCE(:notes, notes)
    WHERE allocation_id = :allocation_id
""")

RESOURCE_POOL_INFO_SQL = text("""
    SELECT res.current_zone_id AS zone_id, res.resource_type,
           (SELECT d.pool_id FROM request_pool_dependency d WHERE d.request_id = :request_id
            ORDER BY d.created_at LIMIT 1) AS pool_id
    FROM resources res WHERE res.resource_id = :resource_id
""")

OUTBOX_SQL = text("""
    INSERT INTO event_outbox (event_id, event_type, pool_id, payload)
    VALUES (:event_id, :event_type, :pool_id, CAST(:payload AS jsonb))
""")

ALLOCATION_ROW_SQL = text("""
    SELECT a.allocation_id, a.request_id, a.resource_id, a.reservation_id, a.quantity_allocated,
           a.allocation_status, a.distance_km, a.priority_score, a.matched_at, a.dispatched_at,
           a.confirmed_at, a.notes,
           r.status AS request_status, r.quantity_requested, r.quantity_fulfilled
    FROM allocations a JOIN emergency_requests r ON r.request_id = a.request_id
    WHERE a.allocation_id = :allocation_id
""")


def _actor_uuid(sub: Optional[str]) -> Optional[str]:
    try:
        return str(uuid.UUID(str(sub)))
    except (TypeError, ValueError):
        return None


def _num(v):
    return float(v) if v is not None else None


async def _emit(db: AsyncSession, event_type: str, request_id, resource_id, payload: dict) -> uuid.UUID:
    info = (await db.execute(RESOURCE_POOL_INFO_SQL, {"request_id": request_id, "resource_id": resource_id})).mappings().first()
    event_id = uuid.uuid4()
    body = {"request_id": str(request_id), "resource_id": str(resource_id), **payload}
    if info:
        # zone_id + resource_type let EventProcessor locate the affected pool(s)
        # for incremental re-matching (same payload shape as LifecycleService).
        body.update({"zone_id": str(info["zone_id"]), "resource_type": info["resource_type"]})
    await db.execute(OUTBOX_SQL, {
        "event_id": event_id, "event_type": event_type,
        "pool_id": info["pool_id"] if info else None, "payload": json.dumps(body, default=str),
    })
    return event_id


async def _allocation_row(db: AsyncSession, allocation_id) -> dict:
    row = dict((await db.execute(ALLOCATION_ROW_SQL, {"allocation_id": allocation_id})).mappings().one())
    for k in ("quantity_allocated", "distance_km", "priority_score", "quantity_requested", "quantity_fulfilled"):
        row[k] = _num(row[k])
    return row


async def _fail(db: AsyncSession, e: exc.DBAPIError, what: str):
    await db.rollback()
    code = _pg_code(e)
    message = str(getattr(e, "orig", e)).split("\n")[0]
    if code == "42501":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role is not permitted to {what}.")
    if code in ("P0001", "23514"):
        # State-machine trigger / CHECK constraint (e.g. invalid transition,
        # insufficient quantity, over-fulfilment).
        raise HTTPException(status.HTTP_409_CONFLICT, f"Rejected by database rules: {message}")
    if code == "23505":
        raise HTTPException(status.HTTP_409_CONFLICT, "This reservation has already been converted into an allocation.")
    if code in ("40P01", "40001", "55P03"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Concurrent update in progress; please retry.")
    logger.exception("Allocation workflow failed (SQLSTATE %s)", code)
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Database error while trying to {what}.")


async def allocate_reservation(db: AsyncSession, reservation_id: uuid.UUID, actor_sub: Optional[str], notes: Optional[str] = None) -> dict:
    try:
        v = (await db.execute(LOCK_RESERVATION_SQL, {"reservation_id": reservation_id})).mappings().first()
        if v is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found.")
        if v["status"] != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, f"Reservation is '{v['status']}', only an active lease can be allocated.")
        if not v["lease_valid"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "The reservation lease has expired; run matching again.")

        r = (await db.execute(LOCK_REQUEST_SQL, {"request_id": v["request_id"]})).mappings().one()
        if r["status"] not in ("open", "pending", "partially_fulfilled"):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Request is '{r['status']}' and cannot receive new allocations.")
        in_flight = float((await db.execute(IN_FLIGHT_QTY_SQL, {"request_id": v["request_id"], "in_flight": list(IN_FLIGHT)})).scalar_one())
        if float(r["quantity_fulfilled"]) + in_flight + float(v["quantity"]) > float(r["quantity_requested"]) + 1e-9:
            raise HTTPException(status.HTTP_409_CONFLICT, "Allocating this reservation would exceed the requested quantity.")

        await db.execute(COMPLETE_RESERVATION_SQL, {"reservation_id": reservation_id})
        allocation_id = uuid.uuid4()
        await db.execute(INSERT_ALLOCATION_SQL, {
            "allocation_id": allocation_id, "reservation_id": reservation_id,
            "actor": _actor_uuid(actor_sub), "notes": notes or f"Allocated from reservation {reservation_id}",
        })
        event_id = await _emit(db, "allocation_created", v["request_id"], v["resource_id"], {
            "allocation_id": str(allocation_id), "reservation_id": str(reservation_id), "quantity": float(v["quantity"]),
        })
        row = await _allocation_row(db, allocation_id)
        await db.commit()
        return {"allocation": row, "event_outbox_id": event_id}
    except HTTPException:
        await db.rollback()
        raise
    except exc.DBAPIError as e:
        await _fail(db, e, "allocate this reservation")


async def release_reservation(db: AsyncSession, reservation_id: uuid.UUID) -> dict:
    try:
        v = (await db.execute(LOCK_RESERVATION_SQL, {"reservation_id": reservation_id})).mappings().first()
        if v is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found.")
        if v["status"] != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, f"Reservation is already '{v['status']}'.")
        await db.execute(RELEASE_RESERVATION_SQL, {"reservation_id": reservation_id})
        event_id = await _emit(db, "resource_returned", v["request_id"], v["resource_id"], {
            "reservation_id": str(reservation_id), "quantity": float(v["quantity"]), "reason": "reservation_released",
        })
        await db.commit()
        return {"reservation_id": reservation_id, "status": "cancelled", "event_outbox_id": event_id}
    except HTTPException:
        await db.rollback()
        raise
    except exc.DBAPIError as e:
        await _fail(db, e, "release this reservation")


async def transition_allocation(db: AsyncSession, allocation_id: uuid.UUID, target: str, notes: Optional[str] = None) -> dict:
    if target not in API_TARGETS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unsupported target status '{target}'.")
    try:
        a = (await db.execute(LOCK_ALLOCATION_SQL, {"allocation_id": allocation_id})).mappings().first()
        if a is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Allocation not found.")
        current = a["allocation_status"]
        if current == target:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Allocation is already '{target}'.")
        if target == "cancelled" and current not in CANCELLABLE_FROM:
            raise HTTPException(status.HTTP_409_CONFLICT, f"An allocation that is '{current}' can no longer be cancelled.")

        # The database state machine validates the transition; on 'confirmed'
        # it rolls quantity_fulfilled and the request status up (and the
        # request guard/audit triggers from migration 0011 fire).
        await db.execute(UPDATE_ALLOCATION_SQL, {"allocation_id": allocation_id, "target": target, "notes": notes})

        event_type = {"confirmed": "allocation_confirmed", "cancelled": "resource_returned"}.get(target, "allocation_status_changed")
        event_id = await _emit(db, event_type, a["request_id"], a["resource_id"], {
            "allocation_id": str(allocation_id), "from": current, "to": target,
            "quantity": float(a["quantity_allocated"]),
            **({"reason": "allocation_cancelled"} if target == "cancelled" else {}),
        })
        row = await _allocation_row(db, allocation_id)
        await db.commit()
        return {"allocation": row, "previous_status": current, "event_outbox_id": event_id}
    except HTTPException:
        await db.rollback()
        raise
    except exc.DBAPIError as e:
        await _fail(db, e, f"move this allocation to '{target}'")
