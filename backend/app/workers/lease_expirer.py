import asyncio
import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from app.models.core import Reservation, EmergencyRequest, Resource, EventOutbox
from app.db.session import service_session
from app.services.matching import MatchingEngine

class LeaseExpirer:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        
    async def process_expirations(self):
        async with self.session_factory() as session:
            now = datetime.datetime.now(datetime.timezone.utc)
            
            # Select expired active reservations, locking them safely
            stmt = select(Reservation).where(
                and_(
                    Reservation.status == 'active',
                    Reservation.lease_expires_at <= now
                )
            ).with_for_update(skip_locked=True)
            
            result = await session.execute(stmt)
            expired_reservations = result.scalars().all()
            
            for res in expired_reservations:
                # 1. Update reservation status
                res.status = 'expired'
                
                # 2. Re-queue request (if not completely fulfilled)
                req = await session.get(EmergencyRequest, res.request_id)
                if req and req.status in ['proposed', 'reserved']:
                    # Revert to pending or open to be re-evaluated
                    req.status = 'pending'
                
                # 3. Create EventOutbox entry triggering re-matching for the affected pool
                # We identify pool by the resource's zone/type
                resource = await session.get(Resource, res.resource_id)
                if resource:
                    event = EventOutbox(
                        event_type="reservation_expired",
                        payload={
                            "reservation_id": str(res.reservation_id),
                            "request_id": str(req.request_id),
                            "resource_id": str(resource.resource_id),
                            "zone_id": str(resource.current_zone_id),
                            "resource_type": resource.resource_type
                        }
                    )
                    session.add(event)
                    
                # Note: DB triggers release quantity based on status='expired'

            await session.commit()

async def run_expirer():
    expirer = LeaseExpirer(service_session)
    while True:
        await expirer.process_expirations()
        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(run_expirer())
