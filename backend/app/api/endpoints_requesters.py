"""Requester profiles (contact details are private; see services/requester_profiles.py)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.schemas.schemas import RequesterContactUpdate, RequesterProfileOut, TokenData
from app.services import requester_profiles

router = APIRouter()


@router.get("/requesters", response_model=list[RequesterProfileOut])
async def list_requesters(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user),
):
    """Coordinator only. Contact details are masked in the list."""
    return await requester_profiles.list_profiles(db, current_user, skip, limit)


@router.get("/requesters/me", response_model=RequesterProfileOut)
async def get_my_profile(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user),
):
    """The calling requester's own profile, including its contact details."""
    if current_user.role != "requester":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a requester has a requester profile.")
    return await requester_profiles.get_profile(db, uuid.UUID(current_user.sub), current_user)


@router.patch("/requesters/me", response_model=RequesterProfileOut)
async def update_my_contact(
    payload: RequesterContactUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user),
):
    """A requester may change only its own contact_phone / contact_email."""
    return await requester_profiles.update_own_contact(db, payload, current_user)


@router.get("/requesters/{requester_id}", response_model=RequesterProfileOut)
async def get_requester(
    requester_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user),
):
    """Full profile for a coordinator or for the requester itself (404 for any
    other requester: RLS hides the row); owners get 403."""
    return await requester_profiles.get_profile(db, requester_id, current_user)
