import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.core import EventOutbox
from app.db.session import service_session
import datetime

class EventProcessor:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        
    async def process_batch(self, batch_size=50):
        async with self.session_factory() as session:
            # Simple select for update skip locked logic for processing
            stmt = select(EventOutbox).where(EventOutbox.processed_at == None).limit(batch_size).with_for_update(skip_locked=True)
            result = await session.execute(stmt)
            events = result.scalars().all()
            
            for event in events:
                try:
                    outcome = await self.handle_event(event)
                    if outcome is not None:
                        event.processing_result = outcome
                    event.processed_at = datetime.datetime.utcnow()
                except Exception as e:
                    # Log error, don't mark processed so it can be retried (or apply retry rules)
                    print(f"Failed to process event {event.event_id}: {e}")
            
            await session.commit()

    async def handle_event(self, event: EventOutbox):
        print(f"Processing event: {event.event_type}, payload: {event.payload}")

        # Resource / hazard changes: same incremental re-matching path as the
        # API's immediate processing (services/rematch.py). Returns the outcome
        # that is stored in event_outbox.processing_result.
        from app.services.rematch import RESOURCE_EVENT_TYPES, run_rematch
        if event.event_type in RESOURCE_EVENT_TYPES:
            result = await run_rematch(self.session_factory, event.event_type, event.payload, event.pool_id)
            result["event_id"] = str(event.event_id)
            return result
        
        # Event-driven re-matching logic (Phase 6 loop closure)
        if event.event_type in ["reservation_expired", "resource_returned", "resource_available"]:
            zone_id = event.payload.get("zone_id")
            resource_type = event.payload.get("resource_type")
            if zone_id and resource_type:
                # Need to find the pool and trigger rematch
                from app.models.core import Pool
                from sqlalchemy import select
                from app.services.matching import MatchingEngine
                
                async with self.session_factory() as session:
                    stmt = select(Pool).where(
                        Pool.zone_id == zone_id,
                        Pool.resource_type == resource_type
                    )
                    # A zone x type can have several pools (one per mobility
                    # class, e.g. requests registered with a 'boat' access
                    # requirement), so re-match every dependent pool.
                    pools = (await session.execute(stmt)).scalars().all()
                    engine = MatchingEngine(session)
                    for pool in pools:
                        await engine.incremental_rematch(pool.pool_id)

async def run_worker():
    processor = EventProcessor(service_session)
    while True:
        await processor.process_batch()
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run_worker())
