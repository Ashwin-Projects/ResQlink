import uuid
import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.core import Allocation, Resource, EmergencyRequest, EventOutbox

class LifecycleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def timeout_dispatched_allocation(self, allocation_id: uuid.UUID):
        """
        Handles failure for dispatched allocations that are not confirmed within timeout.
        """
        alloc = await self.db.get(Allocation, allocation_id)
        if not alloc or alloc.allocation_status != 'dispatched':
            return
            
        # Re-assign or fail
        alloc.allocation_status = 'reassigned'
        
        # Free resource quantity (handled natively by DB triggers, but need to emit event)
        resource = await self.db.get(Resource, alloc.resource_id)
        req = await self.db.get(EmergencyRequest, alloc.request_id)
        
        # Re-queue only an unfulfilled request. A partially_fulfilled /
        # fulfilled request keeps its status (the DB guard trigger from
        # migration 0011 rejects moving it backwards).
        if req and req.status == 'open':
            req.status = 'pending'
            
        event = EventOutbox(
            event_type="resource_returned", # Re-entering availability pool
            payload={
                "allocation_id": str(alloc.allocation_id),
                "resource_id": str(alloc.resource_id),
                "zone_id": str(resource.current_zone_id),
                "resource_type": resource.resource_type,
                "reason": "dispatch_timeout"
            }
        )
        self.db.add(event)
        await self.db.commit()
