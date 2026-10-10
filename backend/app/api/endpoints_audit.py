from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.api.deps import get_db_with_rls, get_current_user
from app.schemas.schemas import TokenData
from app.models.core import EmergencyRequest, Resource
from app.models.base import Base
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, DateTime, JSON, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid

router = APIRouter()

# Defining the history model mapped to the existing allocation_history table
class AllocationHistory(Base):
    __tablename__ = 'allocation_history'
    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(20), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    allocation_id = Column(UUID(as_uuid=True))
    action = Column(String(20), nullable=False)
    old_value = Column(JSONB)
    new_value = Column(JSONB)
    performed_by = Column(UUID(as_uuid=True))
    performed_at = Column(DateTime(timezone=True), nullable=False)
    remarks = Column(String)

@router.get("/requests/{request_id}/history")
async def get_request_history(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    stmt = select(AllocationHistory).where(
        AllocationHistory.entity_type == 'request',
        AllocationHistory.entity_id == request_id
    ).order_by(AllocationHistory.performed_at.asc())
    
    result = await db.execute(stmt)
    history = result.scalars().all()
    return {"history": history}

@router.get("/resources/{resource_id}/history")
async def get_resource_history(
    resource_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    stmt = select(AllocationHistory).where(
        AllocationHistory.entity_type == 'resource',
        AllocationHistory.entity_id == resource_id
    ).order_by(AllocationHistory.performed_at.asc())
    
    result = await db.execute(stmt)
    history = result.scalars().all()
    return {"history": history}

@router.get("/activity-feed")
async def get_activity_feed(
    zone_id: uuid.UUID = None,
    event_type: str = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    # Only coordinators can fetch the global feed typically, restricted via RLS or logic
    stmt = select(AllocationHistory).order_by(AllocationHistory.performed_at.desc()).limit(limit)
    if event_type:
        stmt = stmt.where(AllocationHistory.action == event_type)
        
    result = await db.execute(stmt)
    feed = result.scalars().all()
    return {"feed": feed}
