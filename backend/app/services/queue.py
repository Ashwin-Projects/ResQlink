import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc, or_
from app.models.core import EmergencyRequest
from typing import List
import datetime

class RequestQueueService:
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def get_prioritized_queue(self, pool_id: uuid.UUID = None, limit: int = 100) -> List[EmergencyRequest]:
        """
        Ranked priority queue logic:
        1. Urgency (Critical > High > Medium > Low)
        2. Waiting time (Older requests bumped higher to prevent starvation)
        3. Scarcity/Competition (Pool pressure logic hook)
        """
        # Determine urgency score
        urgency_case = func.case(
            (EmergencyRequest.urgency_level == 'critical', 4),
            (EmergencyRequest.urgency_level == 'high', 3),
            (EmergencyRequest.urgency_level == 'medium', 2),
            (EmergencyRequest.urgency_level == 'low', 1),
            else_=0
        )
        
        # Determine wait time in hours
        wait_hours = func.extract('epoch', func.now() - EmergencyRequest.requested_at) / 3600.0
        
        # Composite score: urgency_weight (e.g. 10 * urgency) + wait_weight (e.g. 0.5 per hour waiting)
        # Prevents starvation: a 'low' request waiting 100 hours scores 10 + 50 = 60
        # A 'critical' request waiting 0 hours scores 40 + 0 = 40. The older request eventually wins.
        composite_score = (urgency_case * 10) + (wait_hours * 0.5)

        stmt = select(EmergencyRequest).where(
            EmergencyRequest.status.in_(['pending', 'open', 'partially_fulfilled'])
        ).order_by(desc(composite_score)).limit(limit)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()
