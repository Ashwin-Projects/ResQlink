from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db_with_rls, get_current_user
from app.schemas.schemas import TokenData, MatchCandidatesOut
from app.services.matching import MatchingEngine
from app.models.core import EmergencyRequest
import datetime
import uuid

router = APIRouter()

@router.post("/requests/{request_id}/match")
async def trigger_match(
    request_id: uuid.UUID,
    mode: str = "incremental",
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    # Coordinator only: the router is mounted with require_coordinator (app/main.py),
    # and api_coordinator holds the INSERT grants on reservation / matching_decision.
    engine = MatchingEngine(db)
    
    try:
        reservations = await engine.match_request(request_id, mode=mode)
        return {"status": "success", "proposed_reservations": reservations}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Matching failed: {str(e)}")

@router.get("/requests/{request_id}/candidates", response_model=MatchCandidatesOut)
async def preview_candidates(
    request_id: uuid.UUID,
    limit: int = 20,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    """Read-only preview of the candidates the matching engine would consider
    for this request (same ST_DWithin retrieval and scoring as match_request).
    Nothing is reserved."""
    engine = MatchingEngine(db)
    try:
        req = await db.get(EmergencyRequest, request_id)
        if req is None:
            raise HTTPException(status_code=404, detail="Emergency request not found.")
        scored = await engine.score_candidates(req, datetime.datetime.now(datetime.timezone.utc))
        committed = await engine.committed_quantity(request_id)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Candidate preview failed: {str(e)}")
    requested, fulfilled = float(req.quantity_requested), float(req.quantity_fulfilled)
    return MatchCandidatesOut(
        request_id=req.request_id,
        request_status=req.status,
        quantity_requested=requested,
        quantity_fulfilled=fulfilled,
        quantity_committed=committed,
        quantity_to_cover=max(0.0, round(requested - fulfilled - committed, 2)),
        max_distance_km=engine.max_distance_meters / 1000.0,
        candidates=[{
            "resource_id": c["resource"].resource_id,
            "resource_type": c["resource"].resource_type,
            "resource_subtype": c["resource"].resource_subtype,
            "owner_id": c["resource"].owner_id,
            "quantity_available": float(c["resource"].quantity_available),
            "unit_of_measure": c["resource"].unit_of_measure,
            "distance_km": round(c["components"]["distance_m"] / 1000.0, 3),
            "score": round(c["score"], 4),
            "score_components": c["components"],
        } for c in scored[:max(1, min(limit, 100))]],
    )

@router.post("/engine/full-rescan")
async def trigger_full_rescan(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    engine = MatchingEngine(db)
    try:
        stats = await engine.full_rescan()
        return {"status": "success", "stats": stats}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/engine/incremental/{pool_id}")
async def trigger_incremental(
    pool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    engine = MatchingEngine(db)
    try:
        stats = await engine.incremental_rematch(pool_id)
        return {"status": "success", "stats": stats}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
