"""Runs the background workers inside the API process.

    FastAPI startup  (app/main.py)  -> BackgroundWorkers.start()
        task "resqlink-outbox"        EventProcessor.process_batch      every OUTBOX_POLL_SECONDS
        task "resqlink-lease-expiry"  LeaseExpirer.process_expirations  every LEASE_EXPIRY_POLL_SECONDS
    FastAPI shutdown                -> BackgroundWorkers.stop(): cancel both tasks and await them

A failing pass is logged and the loop carries on; only cancellation ends it.
Both workers claim rows with FOR UPDATE SKIP LOCKED, so several API processes
(or the standalone `python -m app.workers.*` entry points) can run them at the
same time without processing an event or expiring a lease twice.
"""
import asyncio
import logging
from typing import Awaitable, Callable, List

logger = logging.getLogger("resqlink.workers")


async def run_periodic(name: str, step: Callable[[], Awaitable], interval_seconds: float) -> None:
    """Await `step()` forever, `interval_seconds` apart. An exception from one
    pass is logged and the next pass runs as scheduled; CancelledError
    (shutdown) is not caught and ends the loop."""
    while True:
        try:
            await step()
        except Exception:
            logger.exception("Background worker %s: pass failed; next attempt in %.1fs", name, interval_seconds)
        await asyncio.sleep(interval_seconds)


class BackgroundWorkers:
    def __init__(self, session_factory, outbox_interval: float, lease_interval: float):
        # Imported here so importing this module never pulls in the ORM models.
        from app.workers.event_processor import EventProcessor
        from app.workers.lease_expirer import LeaseExpirer
        self.processor = EventProcessor(session_factory)
        self.expirer = LeaseExpirer(session_factory)
        self.outbox_interval, self.lease_interval = outbox_interval, lease_interval
        self.tasks: List[asyncio.Task] = []

    def start(self) -> None:
        if self.tasks:  # already running
            return
        self.tasks = [
            asyncio.create_task(run_periodic("outbox", self.processor.process_batch, self.outbox_interval),
                                name="resqlink-outbox"),
            asyncio.create_task(run_periodic("lease-expiry", self.expirer.process_expirations, self.lease_interval),
                                name="resqlink-lease-expiry"),
        ]
        logger.info("Background workers started: outbox every %.1fs, lease expiry every %.1fs",
                    self.outbox_interval, self.lease_interval)

    async def stop(self) -> None:
        """Cancel the tasks and wait for them to finish. An in-flight pass is
        interrupted: its transaction rolls back, so an event it had claimed
        stays unprocessed and a lease it had selected stays active until the
        next pass."""
        tasks, self.tasks = self.tasks, []
        for t in tasks:
            t.cancel()
        for t, outcome in zip(tasks, await asyncio.gather(*tasks, return_exceptions=True)):
            if not isinstance(outcome, asyncio.CancelledError) and isinstance(outcome, BaseException):
                logger.error("Background worker task %s ended with %r", t.get_name(), outcome)
        if tasks:
            logger.info("Background workers stopped")
