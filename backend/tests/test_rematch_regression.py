"""Regression tests for services/rematch.py (no database needed).

1. run_rematch passed `started_db.isoformat()` (a str) as the `since` parameter
   of NEW_DECISIONS_SQL (`CAST(:since AS timestamptz)`). asyncpg encodes
   timestamptz parameters only from date/datetime objects, so every resource /
   hazard re-match failed with
       DataError: invalid input for query argument $2: '2026-...'
       (expected a datetime.date or datetime.datetime instance, got 'str')
   and the outbox event was never marked processed. The fake session below
   applies the same type rule as asyncpg's timestamptz encoder.
2. A failed re-match must report `failed` with a safe message (no SQL, no bound
   parameters) while the full exception still reaches the server log.

    cd backend
    python -m pytest -o asyncio_mode=auto tests/test_rematch_regression.py -v
"""
import datetime
import logging
import uuid

import pytest
from sqlalchemy import exc

from app.services import rematch

pytestmark = pytest.mark.asyncio

DB_NOW = datetime.datetime(2026, 10, 10, 16, 39, 34, 2923, tzinfo=datetime.timezone.utc)


class FakeResult:
    def __init__(self, rows=(), scalar=None):
        self._rows, self._scalar = list(rows), scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def one(self):
        return self._rows[0]

    def scalar_one(self):
        return self._scalar


class FakeSession:
    """Answers the statements run_rematch / process_event_now issue; records every call."""

    def __init__(self, log, claim_row=None):
        self.log, self.claim_row = log, claim_row
        self.rolled_back = self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, stmt, params=None):
        self.log.append((stmt, params))
        if stmt is rematch.NEW_DECISIONS_SQL:
            since = params["since"]
            if not isinstance(since, (datetime.date, datetime.datetime)):
                # Same rule (and message) as asyncpg's timestamptz encoder.
                raise TypeError(f"expected a datetime.date or datetime.datetime instance, got {type(since).__name__!r}")
            return FakeResult(rows=[])
        if stmt is rematch.OPEN_REQUESTS_COUNT_SQL:
            return FakeResult(scalar=3)
        if stmt is rematch.DB_NOW_SQL:
            return FakeResult(scalar=DB_NOW)
        if stmt is rematch.CLAIM_EVENT_SQL:
            return FakeResult(rows=[self.claim_row] if self.claim_row else [])
        raise AssertionError(f"unexpected statement: {stmt}")

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakeEngine:
    def __init__(self, session):
        self.session = session

    async def incremental_rematch(self, pool_id):  # pragma: no cover - no pools in these payloads
        raise AssertionError("no pool expected")

    async def match_request(self, request_id, mode="incremental"):  # pragma: no cover
        raise AssertionError("no revoked lease expected")


def factory(log, sessions=None, claim_row=None):
    def make():
        s = FakeSession(log, claim_row)
        if sessions is not None:
            sessions.append(s)
        return s
    return make


async def test_decisions_query_receives_db_timestamp_as_aware_datetime():
    log = []
    result = await rematch.run_rematch(factory(log), "resource_updated", {"rematch_required": True},
                                       engine_factory=FakeEngine)

    assert result["status"] == "processed"
    assert result["open_requests_in_database"] == 3
    (_, params), = [(s, p) for s, p in log if s is rematch.NEW_DECISIONS_SQL]
    since = params["since"]
    # Exactly the value PostgreSQL returned for now(): a datetime, timezone kept.
    assert isinstance(since, datetime.datetime) and since == DB_NOW
    assert since.utcoffset() == datetime.timedelta(0)


async def test_failed_rematch_returns_safe_message_and_logs_details(monkeypatch, caplog):
    event_id = uuid.uuid4()
    raw = ("(sqlalchemy.dialects.postgresql.asyncpg.Error) invalid input for query argument $2: "
           "'2026-10-10T16:39:34.002923+00:00'\n[SQL: SELECT d.request_id FROM matching_decision d]")

    async def failing_rematch(*args, **kwargs):
        raise exc.DBAPIError("SELECT d.request_id FROM matching_decision d", {"since": "x"}, Exception(raw))

    monkeypatch.setattr(rematch, "run_rematch", failing_rematch)
    log, sessions = [], []
    claim_row = {"event_id": event_id, "event_type": "resource_updated", "pool_id": None,
                 "payload": {"rematch_required": True}, "created_at": DB_NOW}

    with caplog.at_level(logging.ERROR, logger=rematch.logger.name):
        result = await rematch.process_event_now(factory(log, sessions, claim_row), event_id)

    # Failure is reported, not hidden.
    assert result["status"] == "failed" and result["event_id"] == str(event_id)
    # No raw SQL / driver text / bound parameter values reach the API response.
    for leaked in ("SELECT", "matching_decision", "query argument", "2026-10-10T16:39:34", "asyncpg", "[SQL"):
        assert leaked not in result["error"]
    assert result["error_type"] == "DBAPIError"
    assert str(event_id) in result["error"] and "unprocessed" in result["error"]
    # The event was not marked processed and the claim was rolled back.
    assert all(s is not rematch.FINISH_EVENT_SQL for s, _ in log)
    assert sessions[0].rolled_back and not sessions[0].committed
    # Full diagnostic detail is still in the server log.
    record, = [r for r in caplog.records if str(event_id) in r.getMessage()]
    assert record.exc_info and "query argument $2" in str(record.exc_info[1])
