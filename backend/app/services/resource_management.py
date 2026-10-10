"""Add / Update Resource (POST /api/v1/resources, PATCH /api/v1/resources/{id}).

Authorization (mirrors the database grants + RLS from migration 0009):
  * coordinator — may create resources for any owner and update any resource
  * owner       — may create/update only resources whose owner_id is its own
                  (token `sub` = owner_id; enforced by RLS owner_resource_policy)
  * requester   — read-only (403)

Quantity model (unchanged schema):
  quantity_total      stock the owner holds
  quantity_available  free stock; reservation/allocation triggers decrement it
  in use              = quantity_total - quantity_available (leased, allocated or consumed)
A stock change of +/-N moves BOTH values by N, so quantities already leased or
allocated to requests are never silently released or double counted; the
total cannot drop below what is in use.

History: trigger fn_log_resource_change (migration 0013) writes
allocation_history, resource_ledger and resource_location_history in the same
transaction. Every change also emits a transactional event_outbox event.
"""
import json
import logging
import re
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import text, exc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import service_session
from app.services.request_intake import _pg_code

logger = logging.getLogger(__name__)

RESOURCE_TYPES = ("generator", "boat", "medical_supply", "shelter_capacity", "volunteer", "vehicle", "other")
UNITS = ("units", "liters", "kits", "seats", "headcount", "vehicles")
# Statuses an operator may set. 'depleted' is derived by fn_resources_sync_status
# from quantity_available; 'allocated' / 'in_transit' are system states.
OPERATOR_STATUSES = ("available", "maintenance", "unavailable")
ALL_STATUSES = ("available", "allocated", "in_transit", "depleted", "maintenance", "unavailable")
RESOURCE_MOBILITY = ("land", "boat", "amphibious", "air")

READ_SQL = """
    SELECT res.resource_id, res.owner_id, o.name AS owner_name, res.current_zone_id, z.zone_name,
           res.resource_type, res.resource_subtype, res.quantity_total, res.quantity_available,
           res.unit_of_measure, res.status, res.condition_notes, res.capabilities,
           res.capabilities ->> 'mobility_class' AS mobility_class,
           res.last_verified_at, res.created_at, res.updated_at,
           ST_Y(res.location::geometry) AS latitude, ST_X(res.location::geometry) AS longitude
    FROM resources res
    JOIN owners o ON o.owner_id = res.owner_id
    JOIN zones z ON z.zone_id = res.current_zone_id
"""

OWNER_EXISTS_SQL = text("SELECT owner_id FROM owners WHERE owner_id = :owner_id")
ZONE_EXISTS_SQL = text("SELECT zone_id FROM zones WHERE zone_id = :zone_id")

INSERT_SQL_TEMPLATE = """
    INSERT INTO resources (resource_id, owner_id, current_zone_id, resource_type, resource_subtype,
                           quantity_total, quantity_available, unit_of_measure, status, location,
                           condition_notes, capabilities, last_verified_at)
    VALUES (:resource_id, :owner_id, :zone_id, :resource_type, :resource_subtype,
            :quantity_total, :quantity_available, :unit_of_measure, :status, {location},
            :condition_notes, CAST(:capabilities AS jsonb), now())
"""
LOCATION_FROM_POINT = "ST_GeogFromText(:ewkt)"
LOCATION_FROM_ZONE = "(SELECT location FROM zones WHERE zone_id = :zone_id)"

LOCK_SQL = text("""
    SELECT resource_id, owner_id, current_zone_id, resource_type, quantity_total, quantity_available,
           status, capabilities
    FROM resources WHERE resource_id = :resource_id
    FOR UPDATE
""")

# Lease revocation goes through SECURITY DEFINER functions (migration 0014): the
# owner role has no privileges on `reservation`; the functions re-check that the
# caller manages this resource and lock the leases FOR UPDATE NOWAIT.
LOCK_LEASES_SQL = text("""
    SELECT reservation_id, request_id, quantity, priority_snapshot, created_at
    FROM fn_lock_resource_leases(:resource_id)
""")
REVOKE_LEASES_SQL = text("""
    SELECT reservation_id, request_id, quantity
    FROM fn_revoke_resource_leases(:resource_id, CAST(:reservation_ids AS uuid[]))
""")
OUT_OF_SERVICE = ("maintenance", "unavailable")
REMATCH_RELEVANT = ("quantity_total", "status", "current_zone_id", "location", "mobility_class")

OUTBOX_SQL = text("""
    INSERT INTO event_outbox (event_id, event_type, pool_id, payload)
    VALUES (:event_id, :event_type, NULL, CAST(:payload AS jsonb))
""")

LEDGER_SQL = text("""
    SELECT id, delta_qty, reason, ref_id, created_at FROM resource_ledger
    WHERE resource_id = :rid ORDER BY created_at DESC, id LIMIT 50
""")
LOCATIONS_SQL = text("""
    SELECT id, ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude,
           recorded_at, source, confidence
    FROM resource_location_history WHERE resource_id = :rid ORDER BY recorded_at DESC, id LIMIT 20
""")
HISTORY_SQL = text("""
    SELECT log_id, action, old_value, new_value, performed_at, remarks FROM allocation_history
    WHERE entity_type = 'resource' AND entity_id = :rid ORDER BY performed_at DESC, log_id LIMIT 50
""")
COMMITMENTS_SQL = text("""
    SELECT COALESCE((SELECT sum(quantity) FROM reservation
                     WHERE resource_id = :rid AND status = 'active'), 0) AS leased,
           COALESCE((SELECT sum(quantity_allocated) FROM allocations
                     WHERE resource_id = :rid
                       AND allocation_status IN ('pending','matched','proposed','reserved','dispatched','in_transit','delivered')), 0) AS allocated
""")

_POINT_RE = re.compile(r"^\s*(?:SRID=4326;)?\s*POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s*$", re.I)


def _num(v):
    return float(v) if v is not None else None


def _json(v):
    """JSONB may arrive decoded (asyncpg codec) or as text depending on the driver setup."""
    return json.loads(v) if isinstance(v, str) else v


def _row(row) -> dict:
    d = dict(row)
    d["capabilities"] = _json(d.get("capabilities"))
    for k in ("quantity_total", "quantity_available"):
        d[k] = _num(d[k])
    d["quantity_in_use"] = round(d["quantity_total"] - d["quantity_available"], 2)
    return d


def point_ewkt(latitude: Optional[float], longitude: Optional[float], wkt: Optional[str]) -> Optional[str]:
    """EWKT for an explicit point, or None to use the zone's point."""
    if latitude is not None and longitude is not None:
        return f"SRID=4326;POINT({float(longitude)} {float(latitude)})"
    if wkt:
        m = _POINT_RE.match(wkt)
        if not m:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "location_wkt must be 'POINT(longitude latitude)'.")
        lng, lat = float(m.group(1)), float(m.group(2))
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "location_wkt coordinates are out of range.")
        return f"SRID=4326;POINT({lng} {lat})"
    return None


def require_manager(user) -> None:
    if user.role not in ("coordinator", "owner"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only coordinators and resource owners can add or update resources.")


async def fetch_resource(db: AsyncSession, resource_id) -> Optional[dict]:
    row = (await db.execute(text(READ_SQL + " WHERE res.resource_id = :rid"), {"rid": resource_id})).mappings().first()
    return _row(row) if row else None


async def list_resources(db: AsyncSession, skip: int, limit: int) -> list:
    rows = (await db.execute(text(READ_SQL + " ORDER BY res.updated_at DESC, res.resource_id OFFSET :skip LIMIT :limit"),
                             {"skip": skip, "limit": limit})).mappings().all()
    return [_row(r) for r in rows]


async def _emit(db: AsyncSession, event_type: str, payload: dict) -> uuid.UUID:
    event_id = uuid.uuid4()
    await db.execute(OUTBOX_SQL, {"event_id": event_id, "event_type": event_type, "payload": json.dumps(payload, default=str)})
    return event_id


async def _fail(db: AsyncSession, e: exc.DBAPIError, what: str):
    await db.rollback()
    code = _pg_code(e)
    if code == "42501":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role is not permitted to {what}.")
    if code in ("23514", "23502", "22003", "22P02", "23503"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Rejected by database constraints while trying to {what}.")
    if code in ("40P01", "40001", "55P03"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Concurrent update in progress; please retry.")
    logger.exception("Resource management failed (SQLSTATE %s)", code)
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Database error while trying to {what}.")


async def create_resource(db: AsyncSession, payload, user) -> dict:
    require_manager(user)
    owner_id = payload.owner_id
    if user.role == "owner":
        if owner_id is not None and str(owner_id) != str(user.sub):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Owners can only register resources they own.")
        owner_id = user.sub
    if owner_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "owner_id is required.")

    total = payload.quantity_total
    available = payload.quantity_available if payload.quantity_available is not None else total
    ewkt = point_ewkt(payload.latitude, payload.longitude, payload.location_wkt)
    capabilities = dict(payload.capabilities or {})
    if payload.mobility_class:
        capabilities["mobility_class"] = payload.mobility_class

    try:
        if (await db.execute(OWNER_EXISTS_SQL, {"owner_id": owner_id})).first() is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown owner_id: no such owner.")
        if (await db.execute(ZONE_EXISTS_SQL, {"zone_id": payload.current_zone_id})).first() is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown current_zone_id: no such zone.")

        resource_id = uuid.uuid4()
        sql = INSERT_SQL_TEMPLATE.format(location=LOCATION_FROM_POINT if ewkt else LOCATION_FROM_ZONE)
        await db.execute(text(sql), {
            "resource_id": resource_id, "owner_id": owner_id, "zone_id": payload.current_zone_id,
            "resource_type": payload.resource_type, "resource_subtype": payload.resource_subtype,
            "quantity_total": total, "quantity_available": available, "unit_of_measure": payload.unit_of_measure,
            "status": payload.status, "ewkt": ewkt, "condition_notes": payload.condition_notes,
            "capabilities": json.dumps(capabilities) if capabilities else None,
        })
        event_id = await _emit(db, "resource_created", {
            "resource_id": str(resource_id), "zone_id": str(payload.current_zone_id), "resource_type": payload.resource_type,
            "quantity_available": float(available), "status": payload.status,
            # New stock can serve pending requests in this zone's pools.
            "affected_zone_ids": [str(payload.current_zone_id)],
            "rematch_required": payload.status == "available" and float(available) > 0,
        })
        created = await fetch_resource(db, resource_id)
        await db.commit()
        return {"resource": created, "event_outbox_id": event_id, "changes": None}
    except HTTPException:
        await db.rollback()
        raise
    except exc.DBAPIError as e:
        await _fail(db, e, "create this resource")


async def update_resource(db: AsyncSession, resource_id: uuid.UUID, payload, user) -> dict:
    require_manager(user)
    fields = payload.model_fields_set
    try:
        cur = (await db.execute(LOCK_SQL, {"resource_id": resource_id})).mappings().first()
        if cur is None:
            # Not found, or not visible to this owner under RLS.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found.")
        if user.role == "owner" and str(cur["owner_id"]) != str(user.sub):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Owners can only update resources they own.")

        sets, params = [], {"resource_id": resource_id}
        changes = {}
        before = {"quantity_total": float(cur["quantity_total"]), "quantity_available": float(cur["quantity_available"]),
                  "status": cur["status"], "current_zone_id": str(cur["current_zone_id"])}

        # ---- Leases that can no longer be honoured are revoked in THIS transaction.
        old_total, old_avail = float(cur["quantity_total"]), float(cur["quantity_available"])
        in_use = round(old_total - old_avail, 2)            # leased + allocated + consumed
        new_total = float(payload.quantity_total) if ("quantity_total" in fields and payload.quantity_total is not None) else old_total
        leaving_service = ("status" in fields and payload.status in OUT_OF_SERVICE and cur["status"] not in OUT_OF_SERVICE)
        revoked = []
        if leaving_service or new_total < in_use:
            leases = [dict(r) for r in (await db.execute(LOCK_LEASES_SQL, {"resource_id": resource_id})).mappings().all()]
            leased = round(sum(float(x["quantity"]) for x in leases), 2)
            floor = round(in_use - leased, 2)                # allocated + consumed: never revoked here
            if new_total < floor:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"{floor:g} units are allocated or consumed; the total cannot go below {floor:g} "
                                    f"(active leases on this resource can be revoked, allocations cannot).")
            if leaving_service:
                to_revoke = leases                           # out of service: no lease can be honoured
            else:
                need, to_revoke = round(in_use - new_total, 2), []
                for x in leases:                             # lowest priority first, then newest
                    if need <= 0:
                        break
                    to_revoke.append(x)
                    need = round(need - float(x["quantity"]), 2)
            if to_revoke:
                rows = (await db.execute(REVOKE_LEASES_SQL, {
                    "resource_id": resource_id,
                    "reservation_ids": [str(x["reservation_id"]) for x in to_revoke],
                })).mappings().all()
                revoked = [{"reservation_id": str(r["reservation_id"]), "request_id": str(r["request_id"]),
                            "quantity": float(r["quantity"])} for r in rows]

        if "quantity_total" in fields and payload.quantity_total is not None:
            delta = round(new_total - old_total, 2)
            if delta != 0:
                sets += ["quantity_total = :quantity_total", "quantity_available = quantity_available + :delta"]
                params.update(quantity_total=payload.quantity_total, delta=delta)
                changes["quantity_total"] = {"from": old_total, "to": new_total}

        if "status" in fields and payload.status is not None and payload.status != cur["status"]:
            sets.append("status = :status")
            params["status"] = payload.status
            changes["status"] = {"from": cur["status"], "to": payload.status}
            if "quantity_available" not in " ".join(sets):
                # Fire fn_resources_sync_status (BEFORE UPDATE OF quantity_available)
                # so the existing DB rule decides: zero stock stays 'depleted'.
                sets.append("quantity_available = quantity_available")

        zone_changed = "current_zone_id" in fields and payload.current_zone_id is not None \
            and str(payload.current_zone_id) != str(cur["current_zone_id"])
        if zone_changed:
            if (await db.execute(ZONE_EXISTS_SQL, {"zone_id": payload.current_zone_id})).first() is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown current_zone_id: no such zone.")
            sets.append("current_zone_id = :zone_id")
            params["zone_id"] = payload.current_zone_id
            changes["current_zone_id"] = {"from": str(cur["current_zone_id"]), "to": str(payload.current_zone_id)}

        ewkt = point_ewkt(payload.latitude, payload.longitude, None)
        if ewkt:
            sets.append("location = ST_GeogFromText(:ewkt)")
            params["ewkt"] = ewkt
            changes["location"] = {"to": {"latitude": payload.latitude, "longitude": payload.longitude}}
        elif zone_changed:
            sets.append("location = (SELECT location FROM zones WHERE zone_id = :zone_id)")
            changes["location"] = {"to": "zone point"}

        if "mobility_class" in fields:
            if payload.mobility_class is None:
                sets.append("capabilities = NULLIF(COALESCE(capabilities, '{}'::jsonb) - 'mobility_class', '{}'::jsonb)")
            else:
                sets.append("capabilities = COALESCE(capabilities, '{}'::jsonb) || jsonb_build_object('mobility_class', CAST(:mobility AS text))")
                params["mobility"] = payload.mobility_class
            changes["mobility_class"] = {"from": (_json(cur["capabilities"]) or {}).get("mobility_class"), "to": payload.mobility_class}

        for col in ("resource_subtype", "condition_notes"):
            if col in fields:
                sets.append(f"{col} = :{col}")
                params[col] = getattr(payload, col)
                changes[col] = {"to": getattr(payload, col)}

        if not sets:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No changes: the submitted values match the current resource.")

        # last_verified_at: an operator update is a fresh verification (temporal
        # confidence) and fires the audit/ledger trigger (migration 0013).
        sets.append("last_verified_at = now()")
        await db.execute(text(f"UPDATE resources SET {', '.join(sets)} WHERE resource_id = :resource_id"), params)

        updated = await fetch_resource(db, resource_id)
        after = {"quantity_total": updated["quantity_total"], "quantity_available": updated["quantity_available"],
                 "status": updated["status"], "current_zone_id": str(updated["current_zone_id"])}
        # Outbox event in the same transaction: everything the re-match needs.
        event_id = await _emit(db, "resource_updated", {
            "resource_id": str(resource_id), "zone_id": str(updated["current_zone_id"]),
            "resource_type": updated["resource_type"], "status": updated["status"],
            "quantity_available": updated["quantity_available"], "changes": changes,
            "before": before, "after": after,
            "affected_zone_ids": list(dict.fromkeys([before["current_zone_id"], after["current_zone_id"]])),
            "revoked_leases": revoked,
            "rematch_required": bool(revoked) or any(k in changes for k in REMATCH_RELEVANT),
        })
        await db.commit()
        return {"resource": updated, "event_outbox_id": event_id, "changes": changes,
                "before": before, "after": after, "revoked_leases": revoked}
    except HTTPException:
        await db.rollback()
        raise
    except exc.DBAPIError as e:
        await _fail(db, e, "update this resource")


async def get_resource_detail(db: AsyncSession, resource_id: uuid.UUID, user) -> dict:
    resource = await fetch_resource(db, resource_id)   # RLS-scoped visibility check
    await db.commit()
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found.")
    # History tables carry no RLS and are not granted to owner/requester roles;
    # read them for this one (RLS-visible) resource through the api_service role.
    async with service_session() as s:
        ledger = [dict(r) for r in (await s.execute(LEDGER_SQL, {"rid": resource_id})).mappings().all()]
        locations = [dict(r) for r in (await s.execute(LOCATIONS_SQL, {"rid": resource_id})).mappings().all()]
        history = [dict(r) for r in (await s.execute(HISTORY_SQL, {"rid": resource_id})).mappings().all()]
        c = (await s.execute(COMMITMENTS_SQL, {"rid": resource_id})).mappings().one()
    for r in ledger:
        r["delta_qty"] = _num(r["delta_qty"])
    for r in locations:
        r["confidence"] = _num(r["confidence"])
    for h in history:
        h["old_value"], h["new_value"] = _json(h["old_value"]), _json(h["new_value"])
    can_edit = user.role == "coordinator" or (user.role == "owner" and str(resource["owner_id"]) == str(user.sub))
    return {
        "resource": resource, "ledger": ledger, "location_history": locations, "history": history,
        "quantity_leased": _num(c["leased"]), "quantity_allocated": _num(c["allocated"]), "can_edit": can_edit,
    }


async def form_options(db: AsyncSession, user) -> dict:
    can_manage = user.role in ("coordinator", "owner")
    owners = []
    if can_manage:
        sql = "SELECT owner_id, name, owner_type, verification_status FROM owners"
        params = {}
        if user.role == "owner":
            sql += " WHERE owner_id::text = :sub"
            params["sub"] = str(user.sub)
        owners = [dict(r) for r in (await db.execute(text(sql + " ORDER BY name"), params)).mappings().all()]
    zones = [dict(r) for r in (await db.execute(text(
        "SELECT zone_id, zone_name, zone_type, risk_level, ST_Y(location::geometry) AS latitude, "
        "ST_X(location::geometry) AS longitude FROM zones ORDER BY zone_name"))).mappings().all()]
    return {
        "owners": owners, "zones": zones, "resource_types": list(RESOURCE_TYPES), "units": list(UNITS),
        "operator_statuses": list(OPERATOR_STATUSES), "all_statuses": list(ALL_STATUSES),
        "mobility_classes": list(RESOURCE_MOBILITY), "current_role": user.role, "can_manage": can_manage,
    }
