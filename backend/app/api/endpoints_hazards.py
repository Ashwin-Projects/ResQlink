"""Pool-level event trigger for the Hazard / Resource-Change simulator.

Writes a real 'hazard_area_updated' event for an existing pool into
event_outbox and processes it through the same incremental re-matching path
as resource changes (services/rematch.py). Every value returned comes from that
execution or from the database; nothing is simulated.
(Hazard polygons themselves are not recomputed here: the event names the pool
whose dependent requests must be re-evaluated.)
"""
import json
import uuid
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls, require_coordinator
from app.db.session import service_session
from app.schemas.schemas import TokenData
from app.services import rematch

router = APIRouter()


class HazardEventSimulate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_type: str = Field(default="hazard_area_updated", pattern="^hazard_area_updated$")
    pool_id: uuid.UUID
    hazard_zone_name: Optional[str] = Field(default=None, max_length=150)
    details: Optional[Dict[str, Any]] = None


@router.post("/trigger-event")
async def trigger_hazard_event(
    event_in: HazardEventSimulate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(require_coordinator),
):
    pool = (await db.execute(text("SELECT pool_id, zone_id, resource_type, mobility_class FROM pool WHERE pool_id = :p"),
                             {"p": event_in.pool_id})).mappings().first()
    if pool is None:
        raise HTTPException(status_code=404, detail="Pool not found.")
    event_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO event_outbox (event_id, event_type, pool_id, payload)
        VALUES (:event_id, 'hazard_area_updated', :pool_id, CAST(:payload AS jsonb))
    """), {"event_id": event_id, "pool_id": event_in.pool_id, "payload": json.dumps({
        "hazard_zone": event_in.hazard_zone_name, "zone_id": str(pool["zone_id"]),
        "resource_type": pool["resource_type"], "affected_pool_ids": [str(event_in.pool_id)],
        "details": event_in.details or {}, "rematch_required": True,
    })})
    await db.commit()
    result = await rematch.process_event_now(service_session, event_id)
    return {"event_outbox_id": str(event_id), "rematch": result}


@router.get("/rematch-runs")
async def list_rematch_runs(
    limit: int = 20,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(require_coordinator),
):
    """Most recent processed re-match events with their stored outcome (event_outbox.processing_result)."""
    return await rematch.recent_runs(db, max(1, min(limit, 100)))
