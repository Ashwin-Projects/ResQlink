"""Reservation -> Allocation workflow endpoints (coordinator only).

Matching itself stays on the existing POST /api/v1/match/requests/{id}/match.
"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls, require_coordinator
from app.schemas.schemas import (
    AllocateReservationIn, AllocationActionOut, AllocationTransitionIn, ReservationReleaseOut, TokenData,
)
from app.services import allocation_flow

router = APIRouter()


@router.post("/reservations/{reservation_id}/allocate", response_model=AllocationActionOut, status_code=201)
async def allocate_reservation(
    reservation_id: uuid.UUID,
    body: AllocateReservationIn | None = None,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(require_coordinator),
):
    """Convert an active, unexpired leased reservation into an allocation
    (status 'reserved'). Exactly once per reservation (row lock + UNIQUE
    allocations.reservation_id)."""
    return await allocation_flow.allocate_reservation(db, reservation_id, current_user.sub, body.notes if body else None)


@router.post("/reservations/{reservation_id}/release", response_model=ReservationReleaseOut)
async def release_reservation(
    reservation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(require_coordinator),
):
    """Cancel an active lease; the database trigger returns its quantity to the resource."""
    return await allocation_flow.release_reservation(db, reservation_id)


@router.post("/allocations/{allocation_id}/transition", response_model=AllocationActionOut)
async def transition_allocation(
    allocation_id: uuid.UUID,
    body: AllocationTransitionIn,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(require_coordinator),
):
    """Move an allocation through the existing database state machine
    (reserved -> dispatched -> [in_transit -> delivered ->] confirmed, or cancelled).
    'confirmed' updates the request's fulfilled quantity and status in the database."""
    return await allocation_flow.transition_allocation(db, allocation_id, body.status, body.notes)
