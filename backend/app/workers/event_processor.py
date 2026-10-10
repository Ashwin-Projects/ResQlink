"""Outbox event processor (background worker, started by app/workers/supervisor.py).

Each pass:
  1. lists unprocessed events older than GRACE_SECONDS (the API processes its
     own resource events right after commit; the worker is the safety net for
     events it could not finish), skipping events that are waiting out a
     retry backoff;
  2. handles each event in its own transaction that claims the row with
     FOR UPDATE SKIP LOCKED AND processed_at IS NULL, so an event is processed
     at most once even with several workers or a concurrent API call:
       * re-matching events (rematch.REMATCH_EVENT_TYPES) go through
         rematch.process_event_now — the same path the API uses; the outcome
         is stored in event_outbox.processing_result;
       * every other event type (request_created, reservation_created,
         allocation_* ...) needs no work and is only marked processed.
A failed event is NEVER marked processed: it stays in the outbox and is retried
with exponential backoff (BASE_BACKOFF_SECONDS doubling up to
MAX_BACKOFF_SECONDS). The attempt count lives in this process only; the
event_outbox table has no attempts / next-retry columns.
"""
import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

from sqlalchemy import text

from app.core.config import settings
from app.db.session import service_session
from app.services import rematch
from app.workers.supervisor import run_periodic

logger = logging.getLogger("resqlink.workers.outbox")

GRACE_SECONDS = 10.0
BASE_BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 300.0

PENDING_EVENTS_SQL = text("""
    SELECT event_id, event_type FROM event_outbox
    WHERE processed_at IS NULL
      AND created_at <= now() - make_interval(secs => :grace_seconds)
      AND NOT (event_id = ANY(CAST(:backoff_ids AS uuid[])))
    ORDER BY created_at, event_id
    LIMIT :limit
""")
MARK_PROCESSED_SQL = text("""
    UPDATE event_outbox SET processed_at = now() WHERE event_id = :event_id AND processed_at IS NULL
""")


class EventProcessor:
    def __init__(self, session_factory, batch_size: int = 50, grace_seconds: float = GRACE_SECONDS,
                 base_backoff: float = BASE_BACKOFF_SECONDS, max_backoff: float = MAX_BACKOFF_SECONDS,
                 clock=time.monotonic):
        self.session_factory = session_factory
        self.batch_size, self.grace_seconds = batch_size, grace_seconds
        self.base_backoff, self.max_backoff = base_backoff, max_backoff
        self.clock = clock
        self.failures: Dict[str, Tuple[int, float]] = {}   # event_id -> (attempts, retry_at)

    def _waiting(self) -> list:
        now = self.clock()
        return [eid for eid, (_, retry_at) in self.failures.items() if retry_at > now]

    def _record_failure(self, event_id: str) -> None:
        attempts = self.failures.get(event_id, (0, 0.0))[0] + 1
        delay = min(self.max_backoff, self.base_backoff * 2 ** (attempts - 1))
        self.failures[event_id] = (attempts, self.clock() + delay)
        logger.warning("Outbox event %s failed (attempt %d); left unprocessed, next retry in %.0fs",
                       event_id, attempts, delay)

    async def process_batch(self) -> dict:
        waiting = self._waiting()
        async with self.session_factory() as s:
            rows = (await s.execute(PENDING_EVENTS_SQL, {
                "grace_seconds": float(self.grace_seconds), "backoff_ids": waiting, "limit": self.batch_size,
            })).mappings().all()
            await s.commit()

        stats = {"processed": 0, "failed": 0, "skipped": 0}
        for row in rows:
            stats[await self.process_event(row["event_id"], row["event_type"])] += 1

        # Forget failures of events that are no longer pending (processed
        # elsewhere): due for retry, yet not returned by a non-full listing.
        if len(rows) < self.batch_size:
            listed, now = {str(r["event_id"]) for r in rows}, self.clock()
            for eid in [e for e, (_, at) in self.failures.items() if at <= now and e not in listed]:
                self.failures.pop(eid, None)
        return stats

    async def process_event(self, event_id, event_type: str) -> str:
        """'processed' | 'failed' (left unprocessed, backoff) | 'skipped' (held by another processor)."""
        key = str(event_id)
        try:
            done = await self._handle(event_id, event_type)
        except Exception:
            logger.exception("Outbox event %s (%s) raised during processing", key, event_type)
            done = False
        if done is None:
            return "skipped"
        if done:
            self.failures.pop(key, None)
            return "processed"
        self._record_failure(key)
        return "failed"

    async def _handle(self, event_id, event_type: str) -> Optional[bool]:
        if event_type in rematch.REMATCH_EVENT_TYPES:
            status = (await rematch.process_event_now(self.session_factory, event_id)).get("status")
            if status == "claimed_by_worker":   # row locked by another processor right now
                return None
            # processed / skipped (stored by process_event_now), already_processed, not_found -> done
            return status != "failed"
        # Informational event: nothing to do except mark it processed.
        async with self.session_factory() as s:
            claimed = (await s.execute(rematch.CLAIM_EVENT_SQL, {"event_id": event_id})).mappings().first()
            if claimed is None:
                await s.rollback()
                return True if await self._is_processed(s, event_id) else None
            await s.execute(MARK_PROCESSED_SQL, {"event_id": event_id})
            await s.commit()
            return True

    async def _is_processed(self, session, event_id) -> bool:
        state = (await session.execute(rematch.EVENT_STATE_SQL, {"event_id": event_id})).mappings().first()
        await session.rollback()
        return state is None or state["processed_at"] is not None


async def run_worker():
    """Standalone entry point: python -m app.workers.event_processor"""
    await run_periodic("outbox", EventProcessor(service_session).process_batch, settings.OUTBOX_POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run_worker())
