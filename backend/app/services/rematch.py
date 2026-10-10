"""Resource change -> outbox -> incremental re-matching (the core invention, wired to real resource changes).

    resource change (POST / PATCH /api/v1/resources, one transaction)
        -> leases that can no longer be honoured are revoked  (reservation 'cancelled', audited)
        -> event_outbox 'resource_created' | 'resource_updated'
             payload: affected zone(s), resource_type, revoked leases + their request IDs
    process_event_now() / EventProcessor (background worker)  — same code path
        -> claim the event row (FOR UPDATE SKIP LOCKED, processed_at IS NULL)
        -> affected pools          = pool rows for (zone in affected zones, resource_type)
        -> affected request IDs    = request_pool_dependency of those pools
                                     + requests whose lease was revoked
        -> MatchingEngine.incremental_rematch(pool) for every affected pool
           MatchingEngine.match_request(...) for revoked-lease requests outside those pools
           (existing engine, unchanged: request row lock, FOR UPDATE SKIP LOCKED leases,
            matching_decision + outbox rows, audit triggers)
        -> event_outbox.processed_at + processing_result (migration 0014)

Every number in processing_result comes from this execution or the database:
before/after snapshots of the affected requests, leases created/revoked, the
count of open requests in the database, and the measured wall-clock time.
"""
import json
import logging
import time
import uuid
from typing import Callable, Iterable

from sqlalchemy import text

logger = logging.getLogger(__name__)

RESOURCE_EVENT_TYPES = ("resource_created", "resource_updated", "hazard_area_updated")
# Resource fields whose change can alter matching results.
REMATCH_RELEVANT_FIELDS = ("quantity_total", "status", "current_zone_id", "location", "mobility_class")
OPEN_STATUSES = ("open", "pending", "partially_fulfilled")

CLAIM_EVENT_SQL = text("""
    SELECT event_id, event_type, pool_id, payload, created_at
    FROM event_outbox
    WHERE event_id = :event_id AND processed_at IS NULL
    FOR UPDATE SKIP LOCKED
""")
EVENT_STATE_SQL = text("""
    SELECT event_id, processed_at, processing_result FROM event_outbox WHERE event_id = :event_id
""")
FINISH_EVENT_SQL = text("""
    UPDATE event_outbox SET processed_at = now(), processing_result = CAST(:result AS jsonb)
    WHERE event_id = :event_id
""")
POOLS_BY_ZONE_SQL = text("""
    SELECT pool_id, zone_id, resource_type, mobility_class FROM pool
    WHERE resource_type = :resource_type AND zone_id = ANY(CAST(:zone_ids AS uuid[]))
    ORDER BY zone_id, mobility_class
""")
POOLS_BY_ID_SQL = text("""
    SELECT pool_id, zone_id, resource_type, mobility_class FROM pool
    WHERE pool_id = ANY(CAST(:pool_ids AS uuid[])) ORDER BY zone_id, mobility_class
""")
DEPENDENTS_SQL = text("""
    SELECT d.pool_id, d.request_id FROM request_pool_dependency d
    WHERE d.pool_id = ANY(CAST(:pool_ids AS uuid[]))
    ORDER BY d.created_at, d.request_id
""")
REQUEST_SNAPSHOT_SQL = text("""
    SELECT r.request_id, r.status, r.resource_type_needed, r.zone_id,
           r.quantity_requested, r.quantity_fulfilled,
           COALESCE((SELECT sum(v.quantity) FROM reservation v
                     WHERE v.request_id = r.request_id AND v.status = 'active' AND v.lease_expires_at > now()), 0) AS leased,
           COALESCE((SELECT sum(a.quantity_allocated) FROM allocations a
                     WHERE a.request_id = r.request_id
                       AND a.allocation_status IN ('pending','matched','proposed','reserved','dispatched','in_transit','delivered')), 0) AS allocated,
           COALESCE((SELECT json_agg(json_build_object('reservation_id', v.reservation_id, 'resource_id', v.resource_id,
                                                       'quantity', v.quantity) ORDER BY v.created_at)
                     FROM reservation v
                     WHERE v.request_id = r.request_id AND v.status = 'active' AND v.lease_expires_at > now()), '[]') AS active_leases
    FROM emergency_requests r
    WHERE r.request_id = ANY(CAST(:request_ids AS uuid[]))
""")
OPEN_REQUESTS_COUNT_SQL = text("""
    SELECT count(*) FROM emergency_requests WHERE status IN ('open','pending','partially_fulfilled')
""")
NEW_DECISIONS_SQL = text("""
    SELECT d.request_id, d.resource_id, d.final_score, d.mode, d.created_at
    FROM matching_decision d
    WHERE d.request_id = ANY(CAST(:request_ids AS uuid[])) AND d.created_at >= CAST(:since AS timestamptz)
    ORDER BY d.created_at
""")
DB_NOW_SQL = text("SELECT now()")


def _num(v):
    return float(v) if v is not None else None


def _json(v):
    return json.loads(v) if isinstance(v, str) else v


def _uuid_list(values: Iterable) -> list:
    return [str(uuid.UUID(str(v))) for v in values]


async def _snapshot(session, request_ids: list) -> dict:
    if not request_ids:
        return {}
    rows = (await session.execute(REQUEST_SNAPSHOT_SQL, {"request_ids": request_ids})).mappings().all()
    out = {}
    for r in rows:
        requested, fulfilled = _num(r["quantity_requested"]), _num(r["quantity_fulfilled"])
        leased, allocated = _num(r["leased"]), _num(r["allocated"])
        leases = _json(r["active_leases"]) or []
        out[str(r["request_id"])] = {
            "status": r["status"],
            "resource_type_needed": r["resource_type_needed"],
            "quantity_requested": requested,
            "quantity_fulfilled": fulfilled,
            "quantity_leased": leased,
            "quantity_allocated": allocated,
            "quantity_to_cover": max(0.0, round(requested - fulfilled - leased - allocated, 2)),
            "active_leases": [{"reservation_id": str(x["reservation_id"]), "resource_id": str(x["resource_id"]),
                               "quantity": _num(x["quantity"])} for x in leases],
        }
    return out


def _default_engine(session):
    from app.services.matching import MatchingEngine  # ORM engine, imported lazily
    return MatchingEngine(session)


async def run_rematch(session_factory: Callable, event_type: str, payload: dict,
                      event_pool_id=None, engine_factory: Callable = _default_engine) -> dict:
    """Incremental re-match for one resource/hazard event. Returns processing_result."""
    payload = payload or {}
    if payload.get("rematch_required") is False:
        return {"status": "skipped", "reason": "no matching-relevant change (notes / subtype only)",
                "affected_pools": [], "affected_requests": [], "requests_evaluated": 0}

    revoked = payload.get("revoked_leases") or []
    revoked_request_ids = list(dict.fromkeys(str(x["request_id"]) for x in revoked))

    async with session_factory() as s:
        # 1. Affected pools.
        explicit = [p for p in (payload.get("affected_pool_ids") or []) if p] + ([str(event_pool_id)] if event_pool_id else [])
        if explicit:
            pools = (await s.execute(POOLS_BY_ID_SQL, {"pool_ids": _uuid_list(set(explicit))})).mappings().all()
        else:
            zone_ids = [z for z in (payload.get("affected_zone_ids") or [payload.get("zone_id")]) if z]
            resource_type = payload.get("resource_type")
            pools = (await s.execute(POOLS_BY_ZONE_SQL, {"resource_type": resource_type, "zone_ids": _uuid_list(set(zone_ids))})).mappings().all() \
                if zone_ids and resource_type else []
        pool_ids = [str(p["pool_id"]) for p in pools]

        # 2. Affected request IDs via the dependency index (+ revoked-lease requests).
        deps = (await s.execute(DEPENDENTS_SQL, {"pool_ids": pool_ids})).mappings().all() if pool_ids else []
        reasons: dict = {}
        req_pools: dict = {}
        for d in deps:
            rid = str(d["request_id"])
            reasons.setdefault(rid, set()).add("pool_dependency")
            req_pools.setdefault(rid, []).append(str(d["pool_id"]))
        for rid in revoked_request_ids:
            reasons.setdefault(rid, set()).add("lease_revoked")
        affected_ids = list(reasons.keys())

        before = await _snapshot(s, affected_ids)
        open_total = int((await s.execute(OPEN_REQUESTS_COUNT_SQL)).scalar_one())
        started_db = (await s.execute(DB_NOW_SQL)).scalar_one()
        await s.commit()

    # 3. Incremental re-matching with the existing engine (each match commits).
    pool_stats = []
    matches_made = 0
    t0 = time.perf_counter()
    async with session_factory() as work:
        engine = engine_factory(work)
        for pid in pool_ids:
            stats = await engine.incremental_rematch(uuid.UUID(pid))
            matches_made += int(stats.get("matches_made", 0))
            pool_stats.append({"pool_id": pid, "requests_examined": int(stats.get("requests_examined", 0)),
                               "matches_made": int(stats.get("matches_made", 0))})
        direct = [rid for rid in revoked_request_ids if "pool_dependency" not in reasons.get(rid, set())]
        for rid in direct:
            made = await engine.match_request(uuid.UUID(rid), mode="incremental")
            matches_made += len(made or [])
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    # 4. After snapshot + decisions recorded during this run.
    async with session_factory() as s:
        after = await _snapshot(s, affected_ids)
        decisions = (await s.execute(NEW_DECISIONS_SQL, {"request_ids": affected_ids or [str(uuid.uuid4())],
                                                         "since": started_db.isoformat()})).mappings().all()
        await s.commit()

    revoked_by_request: dict = {}
    for x in revoked:
        revoked_by_request.setdefault(str(x["request_id"]), []).append(
            {"reservation_id": str(x["reservation_id"]), "quantity": _num(x["quantity"])})
    decisions_by_request: dict = {}
    for d in decisions:
        decisions_by_request.setdefault(str(d["request_id"]), []).append(
            {"resource_id": str(d["resource_id"]), "final_score": _num(d["final_score"]), "mode": d["mode"]})

    keys = ("status", "quantity_leased", "quantity_allocated", "quantity_fulfilled", "quantity_to_cover")
    affected = []
    for rid in affected_ids:
        b, a = before.get(rid, {}), after.get(rid, {})
        before_ids = {x["reservation_id"] for x in b.get("active_leases", [])}
        lost = round(sum(x["quantity"] or 0 for x in revoked_by_request.get(rid, [])), 2)
        before_rematch = {k: b.get(k) for k in keys}
        # State before the resource change = state before re-matching plus the
        # leases the change revoked (same transaction as the change).
        before_change = dict(before_rematch)
        if lost and b:
            before_change["quantity_leased"] = round((b.get("quantity_leased") or 0) + lost, 2)
            before_change["quantity_to_cover"] = max(0.0, round((b.get("quantity_to_cover") or 0) - lost, 2))
        affected.append({
            "request_id": rid,
            "reasons": sorted(reasons[rid]),
            "pool_ids": req_pools.get(rid, []),
            "evaluated": b.get("status") in OPEN_STATUSES,
            "before_change": before_change,
            "before_rematch": before_rematch,
            "after_rematch": {k: a.get(k) for k in keys},
            "leases_revoked": revoked_by_request.get(rid, []),
            "leases_created": [x for x in a.get("active_leases", []) if x["reservation_id"] not in before_ids],
            "decisions": decisions_by_request.get(rid, []),
        })

    return {
        "status": "processed",
        "event_type": event_type,
        "affected_pools": [{"pool_id": str(p["pool_id"]), "zone_id": str(p["zone_id"]),
                            "resource_type": p["resource_type"], "mobility_class": p["mobility_class"]} for p in pools],
        "pool_runs": pool_stats,
        "affected_requests": affected,
        "affected_request_ids": affected_ids,
        "requests_evaluated": sum(1 for x in affected if x["evaluated"]),
        "dependency_rows_examined": len(deps),
        "open_requests_in_database": open_total,
        "matches_made": matches_made,
        "leases_created": sum(len(x["leases_created"]) for x in affected),
        "leases_revoked": len(revoked),
        "elapsed_ms": elapsed_ms,
    }


async def process_event_now(session_factory: Callable, event_id, engine_factory: Callable = _default_engine) -> dict:
    """Claim and process one outbox event immediately (same logic as the worker).

    Safe to call concurrently with the background worker: the event row is
    claimed with FOR UPDATE SKIP LOCKED and only while processed_at IS NULL.
    """
    async with session_factory() as claim:
        ev = (await claim.execute(CLAIM_EVENT_SQL, {"event_id": event_id})).mappings().first()
        if ev is None:
            state = (await claim.execute(EVENT_STATE_SQL, {"event_id": event_id})).mappings().first()
            await claim.rollback()
            if state is None:
                return {"status": "not_found", "event_id": str(event_id)}
            if state["processed_at"] is not None:
                return {**(_json(state["processing_result"]) or {}), "status": "already_processed", "event_id": str(event_id)}
            return {"status": "claimed_by_worker", "event_id": str(event_id)}
        if ev["event_type"] not in RESOURCE_EVENT_TYPES:
            await claim.rollback()
            return {"status": "not_a_rematch_event", "event_id": str(event_id), "event_type": ev["event_type"]}
        try:
            result = await run_rematch(session_factory, ev["event_type"], _json(ev["payload"]), ev["pool_id"], engine_factory)
        except Exception as e:  # leave the event unprocessed so the worker retries it
            logger.exception("Incremental re-match failed for event %s", event_id)
            await claim.rollback()
            return {"status": "failed", "event_id": str(event_id), "error": str(e)}
        result["event_id"] = str(event_id)
        await claim.execute(FINISH_EVENT_SQL, {"event_id": event_id, "result": json.dumps(result, default=str)})
        processed_at = (await claim.execute(EVENT_STATE_SQL, {"event_id": event_id})).mappings().one()["processed_at"]
        await claim.commit()
        result["processed_at"] = processed_at
        return result


RECENT_RUNS_SQL = text("""
    SELECT event_id, event_type, payload, created_at, processed_at, processing_result
    FROM event_outbox
    WHERE processing_result IS NOT NULL
    ORDER BY processed_at DESC
    LIMIT :limit
""")


async def recent_runs(session, limit: int = 20) -> list:
    rows = (await session.execute(RECENT_RUNS_SQL, {"limit": limit})).mappings().all()
    return [{**dict(r), "payload": _json(r["payload"]), "processing_result": _json(r["processing_result"])} for r in rows]
