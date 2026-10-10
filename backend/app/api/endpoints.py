from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.api.deps import get_db_with_rls, get_current_user, require_manager, require_request_party
from app.schemas.schemas import (
    ResourceCreate, ResourceOut, ResourceUpdate, ResourceActionOut, ResourceDetailOut, ResourceFormOptions,
    EmergencyRequestCreate, EmergencyRequestOut, EmergencyRequestCreatedOut,
    RequestFormOptions, RequestTrackingOut, TokenData, RESOURCE_TYPES, URGENCY_LEVELS, MOBILITY_CLASSES,
)
from app.services import request_intake, request_tracking, resource_management, rematch
from app.db.session import service_session
import uuid

router = APIRouter()

@router.get("/resources/form-options", response_model=ResourceFormOptions, dependencies=[Depends(require_manager)])
async def get_resource_form_options(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    """Owners, zones and allowed values for the Add / Edit Resource forms."""
    return await resource_management.form_options(db, current_user)

@router.post("/resources", response_model=ResourceActionOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_manager)])
async def create_resource(
    resource_in: ResourceCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    """Register a resource (coordinator: any owner; owner: itself). One
    transaction: INSERT resources + outbox event; trigger writes audit,
    ledger ('initial_stock') and location history."""
    result = await resource_management.create_resource(db, resource_in, current_user)
    # The change + outbox event are committed; process that event now through
    # the same incremental re-matching path the background worker uses.
    result["rematch"] = await rematch.process_event_now(service_session, result["event_outbox_id"])
    return result

@router.get("/resources", response_model=list[ResourceOut], dependencies=[Depends(require_manager)])
async def list_resources(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db_with_rls)
):
    """Most recently updated first; visibility follows the caller's RLS role."""
    return await resource_management.list_resources(db, skip, limit)

@router.get("/resources/{resource_id}", response_model=ResourceDetailOut, dependencies=[Depends(require_manager)])
async def get_resource(
    resource_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    """Resource with its ledger, location history, audit history and current commitments."""
    return await resource_management.get_resource_detail(db, resource_id, current_user)

@router.patch("/resources/{resource_id}", response_model=ResourceActionOut, dependencies=[Depends(require_manager)])
async def update_resource(
    resource_id: uuid.UUID,
    resource_in: ResourceUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    """Update quantity, status, zone/location, mobility, subtype or notes.

    One transaction: row lock, revocation of leases that can no longer be
    honoured (resource taken out of service, or stock cut below leased
    quantity — allocations are never revoked), audit/ledger triggers and a
    'resource_updated' outbox event. The event is then processed immediately:
    incremental re-matching of only the requests that depend on the affected
    pool(s) (+ requests whose lease was revoked). The real outcome is returned
    in `rematch` and stored in event_outbox.processing_result."""
    result = await resource_management.update_resource(db, resource_id, resource_in, current_user)
    result["rematch"] = await rematch.process_event_now(service_session, result["event_outbox_id"])
    return result

@router.get("/requests/form-options", response_model=RequestFormOptions, dependencies=[Depends(require_request_party)])
async def get_request_form_options(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    """Reference data for the Create Emergency Request form, read live from
    PostgreSQL under the caller's RLS role (a requester only sees itself)."""
    requesters = (await db.execute(text(
        "SELECT requester_id, name, requester_type, verified_flag FROM requesters ORDER BY name LIMIT 1000"
    ))).mappings().all()
    zones = (await db.execute(text(
        "SELECT zone_id, zone_name, zone_type, risk_level, "
        "ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude "
        "FROM zones ORDER BY zone_name"
    ))).mappings().all()
    return RequestFormOptions(
        requesters=[dict(r) for r in requesters],
        zones=[dict(z) for z in zones],
        resource_types=list(RESOURCE_TYPES),
        urgency_levels=list(URGENCY_LEVELS),
        mobility_classes=list(MOBILITY_CLASSES),
        current_role=current_user.role,
    )

@router.post("/requests", response_model=EmergencyRequestCreatedOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_request_party)])
async def create_request(
    request_in: EmergencyRequestCreate,
    response: Response,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    """Create an emergency request (real PostgreSQL transaction).

    201 -> created; 200 -> idempotent replay of an earlier submission that
    used the same idempotency_key (no second row is created).
    """
    created, pool_dependency, event_id, replay = await request_intake.create_emergency_request(db, request_in, current_user)
    if replay:
        response.status_code = status.HTTP_200_OK
    created = (await request_tracking.with_tracking([created]))[0]
    return EmergencyRequestCreatedOut(
        **created,
        pool_dependency=pool_dependency,
        event_outbox_id=event_id,
        idempotent_replay=replay,
    )

@router.get("/requests", response_model=list[EmergencyRequestOut], dependencies=[Depends(require_request_party)])
async def list_requests(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_with_rls)
):
    """Newest first; row visibility follows the caller's RLS role. Each row
    carries its derived tracking stage and remaining/reserved quantities."""
    rows = await request_intake.list_requests(db, skip, limit)
    return await request_tracking.with_tracking(rows)

@router.get("/requests/{request_id}/tracking", response_model=RequestTrackingOut, dependencies=[Depends(require_request_party)])
async def get_request_tracking(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: TokenData = Depends(get_current_user)
):
    """Request Status Tracking: database status, derived tracking stage,
    requested/fulfilled/remaining quantities, assigned resources (leased
    reservations + allocations) and a timestamped timeline from the audit log.
    404 if the request does not exist or is not visible to the caller's role."""
    return await request_tracking.get_request_tracking(db, request_id, current_user.role)
