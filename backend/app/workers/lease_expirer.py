"""Reservation lease expiry (background worker, started by app/workers/supervisor.py).

Each pass, in ONE transaction:
  * locks reservations with status = 'active' AND lease_expires_at <= now()
    (database clock) FOR UPDATE SKIP LOCKED, oldest lease first;
  * sets them to 'expired' — trigger fn_reservations_status_change returns the
    reserved quantity to resources.quantity_available;
  * writes a 'reservation_expired' outbox event (zone_id + resource_type of the
    resource) so EventProcessor re-matches the pools the stock returned to.

Only active leases are touched: 'completed' (converted into an allocation),
'cancelled' and 'expired' reservations never match, and the row lock plus the
status filter mean a lease is expired — and its quantity released — at most
once, even with concurrent expirers or a concurrent allocate / release / revoke
(those lock the same reservation row first and re-check status = 'active').
Request status is not changed here: a request whose lease expired is still
open / pending / partially_fulfilled and stays matchable; its tracking stage is
derived from its active unexpired leases.
"""
import asyncio

from sqlalchemy import select, func

from app.core.config import settings
from app.db.session import service_session
from app.models.core import Reservation, Resource, EventOutbox
from app.workers.supervisor import run_periodic


class LeaseExpirer:
    def __init__(self, session_factory, batch_size: int = 200):
        self.session_factory = session_factory
        self.batch_size = batch_size

    def expired_leases_stmt(self):
        return (select(Reservation)
                .where(Reservation.status == 'active', Reservation.lease_expires_at <= func.now())
                .order_by(Reservation.lease_expires_at)
                .limit(self.batch_size)
                .with_for_update(skip_locked=True))

    async def process_expirations(self) -> int:
        async with self.session_factory() as session:
            expired_reservations = (await session.execute(self.expired_leases_stmt())).scalars().all()

            for res in expired_reservations:
                # The status trigger releases res.quantity back to the resource.
                res.status = 'expired'

                payload = {
                    "reservation_id": str(res.reservation_id),
                    "request_id": str(res.request_id),
                    "resource_id": str(res.resource_id),
                    "quantity": float(res.quantity),
                }
                resource = await session.get(Resource, res.resource_id)
                if resource:
                    # zone_id + resource_type locate the pools for re-matching.
                    payload.update(zone_id=str(resource.current_zone_id), resource_type=resource.resource_type)
                session.add(EventOutbox(event_type="reservation_expired", payload=payload))

            await session.commit()
            return len(expired_reservations)


async def run_expirer():
    """Standalone entry point: python -m app.workers.lease_expirer"""
    await run_periodic("lease-expiry", LeaseExpirer(service_session).process_expirations,
                       settings.LEASE_EXPIRY_POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run_expirer())
