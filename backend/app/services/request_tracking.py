"""Request Status Tracking (GET /api/v1/requests/{id}/tracking).

Everything here is read from PostgreSQL; nothing is stored in a new status.

Database lifecycle (emergency_requests.status, CHECK constraint + the guard
trigger from migration 0011):

    open <-> pending -> partially_fulfilled -> fulfilled
                     \\-> cancelled | expired   (also from partially_fulfilled)

`partially_fulfilled` / `fulfilled` are set ONLY by the database when an
allocation reaches `confirmed` (fn_allocations_on_status_change).

The tracking stage shown to users maps that lifecycle onto
    Pending -> Matching -> Partially Fulfilled -> Fulfilled
where "Matching" is DERIVED, not stored: an open/pending request that
currently holds an active (unexpired) leased reservation or an in-flight
allocation is in the Matching stage.
"""
import uuid
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import text, exc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import service_session
from app.services.request_intake import fetch_request, _pg_code
from app.services.tracking_rules import (
    TERMINAL_STATUSES, IN_FLIGHT_ALLOCATION_STATUSES, build_steps, summarize, _num, _build_timeline,
)

PROGRESS_SQL = text("""
    SELECT ids.request_id,
           COALESCE((SELECT sum(v.quantity) FROM reservation v
                     WHERE v.request_id = ids.request_id AND v.status = 'active'
                       AND v.lease_expires_at > now()), 0)              AS quantity_reserved,
           COALESCE((SELECT sum(a.quantity_allocated) FROM allocations a
                     WHERE a.request_id = ids.request_id
                       AND a.allocation_status = ANY(CAST(:in_flight AS text[]))), 0) AS quantity_in_progress,
           (EXISTS (SELECT 1 FROM reservation v WHERE v.request_id = ids.request_id)
            OR EXISTS (SELECT 1 FROM allocations a WHERE a.request_id = ids.request_id)) AS ever_matched
    FROM unnest(CAST(:ids AS uuid[])) AS ids(request_id)
""")


async def fetch_progress(request_ids: Iterable[uuid.UUID]) -> dict:
    """Reservation / allocation aggregates per request.

    Callers must pass only request ids that the caller's RLS-scoped session
    could already read. reservation/allocations carry no RLS policies and are
    not granted to api_requester, so these child rows are read through the
    api_service role (no contact columns, no writes needed here), strictly
    filtered to those ids.
    """
    ids = [uuid.UUID(str(i)) for i in request_ids]
    if not ids:
        return {}
    async with service_session() as session:
        rows = (await session.execute(PROGRESS_SQL, {"ids": ids, "in_flight": list(IN_FLIGHT_ALLOCATION_STATUSES)})).mappings().all()
    return {str(r["request_id"]): {
        "quantity_reserved": float(r["quantity_reserved"]),
        "quantity_in_progress": float(r["quantity_in_progress"]),
        "ever_matched": bool(r["ever_matched"]),
    } for r in rows}


async def with_tracking(rows: list) -> list:
    progress = await fetch_progress(r["request_id"] for r in rows)
    return [{**r, **summarize(r, progress.get(str(r["request_id"])))} for r in rows]


RESERVATIONS_SQL = text("""
    SELECT v.reservation_id, v.resource_id, res.resource_type, res.resource_subtype, res.unit_of_measure,
           o.name AS owner_name, v.quantity, v.status, v.lease_expires_at,
           (v.status = 'active' AND v.lease_expires_at > now()) AS lease_active,
           v.priority_snapshot, v.created_at, v.updated_at,
           al.allocation_id, md.final_score, md.score_components, md.mode AS match_mode
    FROM reservation v
    JOIN resources res ON res.resource_id = v.resource_id
    JOIN owners o ON o.owner_id = res.owner_id
    LEFT JOIN allocations al ON al.reservation_id = v.reservation_id
    LEFT JOIN LATERAL (
        SELECT d.final_score, d.score_components, d.mode
        FROM matching_decision d
        WHERE d.request_id = v.request_id AND d.resource_id = v.resource_id AND d.created_at <= v.created_at
        ORDER BY d.created_at DESC LIMIT 1
    ) md ON true
    WHERE v.request_id = :rid
    ORDER BY v.created_at
""")

ALLOCATIONS_SQL = text("""
    SELECT a.allocation_id, a.resource_id, res.resource_type, res.resource_subtype, res.unit_of_measure,
           o.name AS owner_name, a.quantity_allocated, a.allocation_status, a.distance_km,
           a.matched_at, a.dispatched_at, a.confirmed_at,
           a.reservation_id, a.priority_score, a.notes
    FROM allocations a
    JOIN resources res ON res.resource_id = a.resource_id
    JOIN owners o ON o.owner_id = res.owner_id
    WHERE a.request_id = :rid
    ORDER BY a.matched_at
""")

HISTORY_SQL = text("""
    SELECT h.log_id, h.entity_type, h.entity_id, h.allocation_id, h.action,
           h.old_value, h.new_value, h.performed_at, h.remarks
    FROM allocation_history h
    WHERE (h.entity_type = 'request' AND h.entity_id = :rid)
       OR h.allocation_id IN (SELECT allocation_id FROM allocations WHERE request_id = :rid)
    ORDER BY h.performed_at, h.log_id
""")


async def get_request_tracking(db: AsyncSession, request_id: uuid.UUID, viewer_role: str = "coordinator") -> dict:
    # 1. Visibility check under the caller's RLS role.
    try:
        request = await fetch_request(db, request_id)
        await db.commit()
    except exc.DBAPIError as e:
        await db.rollback()
        if _pg_code(e) == "42501":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not permitted to view emergency requests.")
        raise
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Emergency request not found.")

    # 2. Child rows of that one request (see fetch_progress for why).
    async with service_session() as session:
        reservations = [dict(r) for r in (await session.execute(RESERVATIONS_SQL, {"rid": request_id})).mappings().all()]
        allocations = [dict(r) for r in (await session.execute(ALLOCATIONS_SQL, {"rid": request_id})).mappings().all()]
        history = [dict(r) for r in (await session.execute(HISTORY_SQL, {"rid": request_id})).mappings().all()]
        as_of = (await session.execute(text("SELECT now()"))).scalar_one()
    progress = (await fetch_progress([request_id])).get(str(request_id))

    summary = summarize(request, progress)
    for r in reservations:
        r["quantity"] = _num(r["quantity"])
        r["priority_snapshot"] = _num(r["priority_snapshot"])
        r["final_score"] = _num(r["final_score"])
    for a in allocations:
        a["quantity_allocated"] = _num(a["quantity_allocated"])
        a["distance_km"] = _num(a["distance_km"])
        a["priority_score"] = _num(a["priority_score"])

    last_change = max([request["updated_at"]] + [r["updated_at"] for r in reservations]
                      + [h["performed_at"] for h in history])
    return {
        "request": {**request, **summary},
        "stage": summary["tracking_stage"],
        "db_status": request["status"],
        "is_terminal": request["status"] in TERMINAL_STATUSES,
        "steps": build_steps(summary["tracking_stage"], summary["ever_matched"], float(request["quantity_fulfilled"])),
        "quantities": {
            "requested": float(request["quantity_requested"]),
            "fulfilled": float(request["quantity_fulfilled"]),
            "remaining": summary["quantity_remaining"],
            "reserved": summary["quantity_reserved"],
            "in_progress": summary["quantity_in_progress"],
        },
        "reservations": reservations,
        "allocations": allocations,
        "timeline": _build_timeline(request, reservations, history),
        "last_change_at": last_change,
        "as_of": as_of,
        "quantity_to_cover": max(0.0, round(summary["quantity_remaining"] - summary["quantity_reserved"]
                                            - summary["quantity_in_progress"], 2)),
        "viewer_role": viewer_role,
        "can_manage": viewer_role == "coordinator",
    }
