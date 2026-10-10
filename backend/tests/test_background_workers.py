"""Background workers: lifecycle, outbox retry / duplicate protection, lease expiry.

No database: every session below is an in-memory fake, and the FastAPI startup
test stubs the one startup check that would connect. What these tests cannot
show — PostgreSQL row locking under real concurrency and the quantity release
done by trigger fn_reservations_status_change — still needs an isolated
PostgreSQL integration run.

    cd backend
    python -m pytest -o asyncio_mode=auto tests/test_background_workers.py -v
"""
import asyncio
import logging
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

import app.main as main
from app.models.core import EventOutbox, Reservation, Resource
from app.services import rematch
from app.workers import event_processor as ep
from app.workers.event_processor import EventProcessor
from app.workers.lease_expirer import LeaseExpirer
from app.workers.supervisor import BackgroundWorkers, run_periodic

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- lifecycle

async def test_run_periodic_logs_failures_and_keeps_running(caplog):
    calls = []

    async def step():
        calls.append(1)
        if len(calls) <= 2:
            raise RuntimeError("boom")

    task = asyncio.create_task(run_periodic("test", step, 0))
    while len(calls) < 4:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 4
    assert sum("pass failed" in r.getMessage() for r in caplog.records) == 2


async def test_background_workers_start_and_stop_cleanly():
    workers = BackgroundWorkers(lambda: None, 0, 0)
    ran = {"outbox": 0, "lease": 0}

    async def outbox():
        ran["outbox"] += 1

    async def lease():
        ran["lease"] += 1

    workers.processor.process_batch, workers.expirer.process_expirations = outbox, lease
    workers.start()
    first = list(workers.tasks)
    workers.start()                                   # second start is a no-op
    assert workers.tasks == first and len(first) == 2
    assert {t.get_name() for t in first} == {"resqlink-outbox", "resqlink-lease-expiry"}
    while ran["outbox"] < 2 or ran["lease"] < 2:
        await asyncio.sleep(0)

    await workers.stop()
    assert workers.tasks == [] and all(t.done() and t.cancelled() for t in first)
    await workers.stop()                              # stopping twice is harmless


class FakeWorkers:
    instances = []

    def __init__(self, session_factory, outbox_interval, lease_interval):
        self.args = (session_factory, outbox_interval, lease_interval)
        self.started = self.stopped = False
        FakeWorkers.instances.append(self)

    def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


async def _no_db_check():
    return False


async def test_fastapi_lifespan_starts_and_stops_workers(monkeypatch):
    FakeWorkers.instances = []
    monkeypatch.setattr(main, "BackgroundWorkers", FakeWorkers)
    monkeypatch.setattr(main, "database_login_is_privileged", _no_db_check)
    monkeypatch.setattr(main.settings, "BACKGROUND_WORKERS_ENABLED", True)
    monkeypatch.delattr(main.app.state, "background_workers", raising=False)

    async with main.app.router.lifespan_context(main.app):
        w, = FakeWorkers.instances
        assert w.started and not w.stopped
        assert w.args == (main.service_session, main.settings.OUTBOX_POLL_SECONDS, main.settings.LEASE_EXPIRY_POLL_SECONDS)
    assert w.stopped


async def test_workers_not_started_when_disabled(monkeypatch, caplog):
    FakeWorkers.instances = []
    monkeypatch.setattr(main, "BackgroundWorkers", FakeWorkers)
    monkeypatch.setattr(main, "database_login_is_privileged", _no_db_check)
    monkeypatch.setattr(main.settings, "BACKGROUND_WORKERS_ENABLED", False)
    monkeypatch.delattr(main.app.state, "background_workers", raising=False)

    async with main.app.router.lifespan_context(main.app):
        assert FakeWorkers.instances == []
    assert any("BACKGROUND_WORKERS_ENABLED is false" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- outbox processor

class Outbox:
    """In-memory event_outbox with row locks held until commit / rollback."""

    def __init__(self):
        self.events = {}            # str(event_id) -> {"type", "processed", "locked_by"}

    def add(self, event_type, locked_by=None):
        eid = uuid.uuid4()
        self.events[str(eid)] = {"type": event_type, "processed": False, "locked_by": locked_by}
        return eid


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        row, = self.rows
        return row


class OutboxSession:
    def __init__(self, outbox, log):
        self.outbox, self.log, self.held = outbox, log, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        await self.rollback()

    async def execute(self, stmt, params):
        self.log.append((stmt, params))
        ev = self.outbox.events.get(str(params.get("event_id")))
        if stmt is ep.PENDING_EVENTS_SQL:
            assert params["grace_seconds"] == ep.GRACE_SECONDS
            skip = set(map(str, params["backoff_ids"]))
            rows = [{"event_id": uuid.UUID(k), "event_type": e["type"]} for k, e in self.outbox.events.items()
                    if not e["processed"] and k not in skip]
            return Result(rows[:params["limit"]])
        if stmt is rematch.CLAIM_EVENT_SQL:          # FOR UPDATE SKIP LOCKED ... processed_at IS NULL
            if ev is None or ev["processed"] or ev["locked_by"] is not None:
                return Result([])
            ev["locked_by"] = self
            self.held.append(ev)
            return Result([{"event_id": params["event_id"], "event_type": ev["type"]}])
        if stmt is ep.MARK_PROCESSED_SQL:
            assert ev["locked_by"] is self, "marked processed without holding the claim"
            ev["processed"] = True
            return Result([])
        if stmt is rematch.EVENT_STATE_SQL:
            return Result([{"processed_at": "t" if ev["processed"] else None}] if ev else [])
        raise AssertionError(f"unexpected statement {stmt}")

    def _release(self):
        for ev in self.held:
            if ev["locked_by"] is self:
                ev["locked_by"] = None
        self.held = []

    async def commit(self):
        self._release()

    async def rollback(self):
        self._release()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_processor(outbox, log, **kw):
    clock = Clock()
    return EventProcessor(lambda: OutboxSession(outbox, log), clock=clock, **kw), clock


def fake_process_event_now(outbox, script, calls):
    """Stands in for rematch.process_event_now: pops the next status for the
    event from `script`; 'processed' marks it processed like the real one."""
    async def fake(session_factory, event_id, *a, **kw):
        calls.append(str(event_id))
        status = script[str(event_id)].pop(0)
        if isinstance(status, Exception):
            raise status
        if status == "processed":
            outbox.events[str(event_id)]["processed"] = True
        return {"status": status, "event_id": str(event_id)}
    return fake


async def test_failed_event_stays_unprocessed_and_retries_with_backoff(monkeypatch):
    outbox, log, calls = Outbox(), [], []
    eid = outbox.add("resource_updated")
    monkeypatch.setattr(rematch, "process_event_now",
                        fake_process_event_now(outbox, {str(eid): ["failed", "failed", "processed"]}, calls))
    proc, clock = make_processor(outbox, log, base_backoff=5, max_backoff=300)

    assert await proc.process_batch() == {"processed": 0, "failed": 1, "skipped": 0}
    assert outbox.events[str(eid)]["processed"] is False           # never marked processed on failure
    assert proc.failures[str(eid)] == (1, clock.now + 5)

    assert await proc.process_batch() == {"processed": 0, "failed": 0, "skipped": 0}   # still in backoff
    assert calls == [str(eid)]

    clock.now += 5
    await proc.process_batch()                                     # second attempt fails: delay doubles
    assert proc.failures[str(eid)] == (2, clock.now + 10) and outbox.events[str(eid)]["processed"] is False

    clock.now += 10
    assert await proc.process_batch() == {"processed": 1, "failed": 0, "skipped": 0}
    assert outbox.events[str(eid)]["processed"] is True and str(eid) not in proc.failures
    assert calls == [str(eid)] * 3
    assert all(s is not ep.MARK_PROCESSED_SQL for s, _ in log)     # re-match events are marked by process_event_now only


async def test_backoff_is_capped():
    proc, clock = make_processor(Outbox(), [], base_backoff=5, max_backoff=60)
    for _ in range(10):
        proc._record_failure("e")
    assert proc.failures["e"] == (10, clock.now + 60)


async def test_exception_in_one_event_does_not_stop_the_batch(monkeypatch):
    outbox, log, calls = Outbox(), [], []
    bad, good = outbox.add("resource_updated"), outbox.add("resource_created")
    monkeypatch.setattr(rematch, "process_event_now", fake_process_event_now(
        outbox, {str(bad): [RuntimeError("driver down")], str(good): ["processed"]}, calls))
    proc, _ = make_processor(outbox, log)

    assert await proc.process_batch() == {"processed": 1, "failed": 1, "skipped": 0}
    assert outbox.events[str(bad)]["processed"] is False and str(bad) in proc.failures
    assert outbox.events[str(good)]["processed"] is True


async def test_informational_event_is_marked_processed_exactly_once(monkeypatch):
    outbox, log = Outbox(), []
    eid = outbox.add("allocation_created")

    async def must_not_run(*a, **kw):
        raise AssertionError("informational events are not re-matched")
    monkeypatch.setattr(rematch, "process_event_now", must_not_run)
    proc, _ = make_processor(outbox, log)

    assert await proc.process_batch() == {"processed": 1, "failed": 0, "skipped": 0}
    assert await proc.process_batch() == {"processed": 0, "failed": 0, "skipped": 0}
    assert sum(s is ep.MARK_PROCESSED_SQL for s, _ in log) == 1


async def test_event_held_by_another_processor_is_skipped_without_backoff(monkeypatch):
    outbox, log, calls = Outbox(), [], []
    info = outbox.add("request_created", locked_by="other worker")      # row locked elsewhere
    rm_event = outbox.add("resource_updated")
    monkeypatch.setattr(rematch, "process_event_now",
                        fake_process_event_now(outbox, {str(rm_event): ["claimed_by_worker"]}, calls))
    proc, _ = make_processor(outbox, log)

    assert await proc.process_batch() == {"processed": 0, "failed": 0, "skipped": 2}
    assert not outbox.events[str(info)]["processed"] and not outbox.events[str(rm_event)]["processed"]
    assert proc.failures == {}
    assert all(s is not ep.MARK_PROCESSED_SQL for s, _ in log)


async def test_already_processed_event_counts_as_done(monkeypatch):
    outbox, calls = Outbox(), []
    eid = outbox.add("resource_updated")
    monkeypatch.setattr(rematch, "process_event_now",
                        fake_process_event_now(outbox, {str(eid): ["already_processed"]}, calls))
    proc, _ = make_processor(outbox, [])
    assert await proc.process_batch() == {"processed": 1, "failed": 0, "skipped": 0}


async def test_claim_and_listing_sql_guard_against_duplicates():
    claim = " ".join(str(rematch.CLAIM_EVENT_SQL).split())
    assert "processed_at IS NULL" in claim and "FOR UPDATE SKIP LOCKED" in claim
    assert "processed_at IS NULL" in str(ep.MARK_PROCESSED_SQL)
    listing = " ".join(str(ep.PENDING_EVENTS_SQL).split())
    assert "processed_at IS NULL" in listing and ":grace_seconds" in listing and ":backoff_ids" in listing


# --------------------------------------------------------------------------- return events -> re-match

class ClaimSession:
    def __init__(self, row, log):
        self.row, self.log = row, log
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        self.log.append(stmt)
        if stmt is rematch.CLAIM_EVENT_SQL:
            return Result([self.row])
        if stmt is rematch.EVENT_STATE_SQL:
            return Result([{"processed_at": "now"}])
        if stmt is rematch.FINISH_EVENT_SQL:
            return Result([])
        raise AssertionError(stmt)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


@pytest.mark.parametrize("event_type,expected_pool", [
    ("reservation_expired", None), ("resource_returned", None),       # pools from payload zone x type
    ("resource_updated", "pool-1"),                                    # explicit event pool kept
])
async def test_process_event_now_routes_rematch_events(monkeypatch, event_type, expected_pool):
    seen, log = {}, []

    async def fake_run_rematch(session_factory, etype, payload, pool_id, engine_factory):
        seen.update(etype=etype, payload=payload, pool_id=pool_id)
        return {"status": "processed"}
    monkeypatch.setattr(rematch, "run_rematch", fake_run_rematch)
    payload = {"zone_id": "z", "resource_type": "boat"}
    row = {"event_id": "e", "event_type": event_type, "pool_id": "pool-1", "payload": payload, "created_at": None}

    result = await rematch.process_event_now(lambda: ClaimSession(row, log), "e")
    assert result["status"] == "processed"
    assert seen == {"etype": event_type, "payload": payload, "pool_id": expected_pool}
    assert rematch.FINISH_EVENT_SQL in log


# --------------------------------------------------------------------------- lease expiry

async def test_expiry_query_selects_only_active_expired_leases_with_skip_locked():
    sql = str(LeaseExpirer(None, batch_size=7).expired_leases_stmt().compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    flat = " ".join(sql.split())
    assert "reservation.status = 'active'" in flat
    assert "reservation.lease_expires_at <= now()" in flat         # database clock, not the app clock
    assert flat.endswith("LIMIT 7 FOR UPDATE SKIP LOCKED")


class ExpirySession:
    def __init__(self, reservations, resources):
        self.reservations, self.resources = reservations, resources
        self.added, self.commits, self.statements = [], 0, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        self.statements.append(stmt)
        rows = self.reservations

        class R:
            def scalars(self):
                return self

            def all(self):
                return rows
        return R()

    async def get(self, model, key):
        assert model is Resource
        return self.resources.get(key)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


def _lease(**kw):
    return Reservation(reservation_id=uuid.uuid4(), request_id=uuid.uuid4(), resource_id=uuid.uuid4(),
                       quantity=Decimal("3.50"), status="active", **kw)


async def test_lease_expiry_expires_and_emits_rematch_event():
    lease = _lease()
    zone = uuid.uuid4()
    resource = Resource(resource_id=lease.resource_id, current_zone_id=zone, resource_type="boat")
    session = ExpirySession([lease], {lease.resource_id: resource})

    assert await LeaseExpirer(lambda: session).process_expirations() == 1
    assert lease.status == "expired"          # trigger fn_reservations_status_change releases the quantity
    assert session.commits == 1
    event, = session.added
    assert isinstance(event, EventOutbox) and event.event_type == "reservation_expired"
    assert event.payload == {"reservation_id": str(lease.reservation_id), "request_id": str(lease.request_id),
                             "resource_id": str(lease.resource_id), "quantity": 3.5,
                             "zone_id": str(zone), "resource_type": "boat"}
    assert event.event_type in rematch.RETURN_EVENT_TYPES


async def test_lease_expiry_without_resource_row_still_expires():
    lease = _lease()
    session = ExpirySession([lease], {})
    assert await LeaseExpirer(lambda: session).process_expirations() == 1
    assert lease.status == "expired" and "zone_id" not in session.added[0].payload


async def test_lease_expiry_with_nothing_due_changes_nothing():
    session = ExpirySession([], {})
    assert await LeaseExpirer(lambda: session).process_expirations() == 0
    assert session.added == [] and session.commits == 1
