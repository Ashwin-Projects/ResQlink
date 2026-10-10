from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal
from uuid import UUID
from decimal import Decimal
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Resources
# Allowed values mirror the CHECK constraints on resources (schema.sql / 0003).
# ---------------------------------------------------------------------------
ResourceTypeLiteral = Literal['generator', 'boat', 'medical_supply', 'shelter_capacity', 'volunteer', 'vehicle', 'other']
UnitLiteral = Literal['units', 'liters', 'kits', 'seats', 'headcount', 'vehicles']
# Operator-settable statuses; 'depleted' is derived by the database from quantity_available.
OperatorStatusLiteral = Literal['available', 'maintenance', 'unavailable']
ResourceMobilityLiteral = Literal['land', 'boat', 'amphibious', 'air']
QTY = dict(ge=0, max_digits=10, decimal_places=2)


def _check_capabilities(v):
    if v is None:
        return v
    if len(v) > 20 or len(str(v)) > 2000:
        raise ValueError('capabilities is limited to 20 keys / 2000 characters')
    if 'mobility_class' in v and v['mobility_class'] not in ('land', 'boat', 'amphibious', 'air'):
        raise ValueError("capabilities.mobility_class must be one of land, boat, amphibious, air")
    return v


class ResourceCreate(BaseModel):
    """Payload for POST /api/v1/resources.
    Location precedence: latitude/longitude > location_wkt > the zone's point."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    owner_id: Optional[UUID] = None             # owner role: defaults to (and must equal) the token's owner id
    current_zone_id: UUID
    resource_type: ResourceTypeLiteral
    resource_subtype: Optional[str] = Field(default=None, max_length=100)
    quantity_total: Decimal = Field(**QTY)
    quantity_available: Optional[Decimal] = Field(default=None, **QTY)   # default: = quantity_total
    unit_of_measure: UnitLiteral
    status: OperatorStatusLiteral = 'available'
    mobility_class: Optional[ResourceMobilityLiteral] = None
    capabilities: Optional[Dict[str, Any]] = None
    condition_notes: Optional[str] = Field(default=None, max_length=1000)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    location_wkt: Optional[str] = Field(default=None, max_length=200)

    @field_validator('resource_subtype', 'condition_notes', 'location_wkt')
    @classmethod
    def _blank_to_none(cls, v):
        return None if isinstance(v, str) and v == '' else v

    @field_validator('capabilities')
    @classmethod
    def _caps(cls, v):
        return _check_capabilities(v)

    @model_validator(mode='after')
    def _consistency(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('latitude and longitude must be provided together')
        if self.quantity_available is not None and self.quantity_available > self.quantity_total:
            raise ValueError('quantity_available cannot exceed quantity_total')
        return self


class ResourceUpdate(BaseModel):
    """Payload for PATCH /api/v1/resources/{id}; only the fields sent are changed."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    quantity_total: Optional[Decimal] = Field(default=None, **QTY)
    status: Optional[OperatorStatusLiteral] = None
    current_zone_id: Optional[UUID] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    mobility_class: Optional[ResourceMobilityLiteral] = None   # explicit null removes it
    resource_subtype: Optional[str] = Field(default=None, max_length=100)
    condition_notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator('resource_subtype', 'condition_notes')
    @classmethod
    def _blank_to_none(cls, v):
        return None if isinstance(v, str) and v == '' else v

    @model_validator(mode='after')
    def _consistency(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('latitude and longitude must be provided together')
        if not self.model_fields_set:
            raise ValueError('at least one field must be provided')
        for f in ('quantity_total', 'status', 'current_zone_id'):
            if f in self.model_fields_set and getattr(self, f) is None:
                raise ValueError(f'{f} cannot be null')
        return self


class ResourceOut(BaseModel):
    resource_id: UUID
    owner_id: UUID
    owner_name: Optional[str] = None
    current_zone_id: UUID
    zone_name: Optional[str] = None
    resource_type: str
    resource_subtype: Optional[str] = None
    quantity_total: float
    quantity_available: float
    quantity_in_use: Optional[float] = None       # total - available: leased, allocated or consumed
    unit_of_measure: str
    status: str
    condition_notes: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    mobility_class: Optional[str] = None
    last_verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    model_config = ConfigDict(from_attributes=True)


class ResourceActionOut(BaseModel):
    resource: ResourceOut
    changes: Optional[Dict[str, Any]] = None
    event_outbox_id: Optional[UUID] = None
    before: Optional[Dict[str, Any]] = None              # resource state before the change
    after: Optional[Dict[str, Any]] = None               # resource state after the change
    revoked_leases: Optional[List[Dict[str, Any]]] = None
    # Outcome of processing the outbox event (incremental re-matching), as stored
    # in event_outbox.processing_result — see services/rematch.py.
    rematch: Optional[Dict[str, Any]] = None


class ResourceLedgerEntry(BaseModel):
    id: UUID
    delta_qty: float
    reason: str
    ref_id: Optional[UUID] = None
    created_at: datetime


class ResourceLocationEntry(BaseModel):
    id: UUID
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    recorded_at: datetime
    source: Optional[str] = None
    confidence: Optional[float] = None


class ResourceHistoryEntry(BaseModel):
    log_id: UUID
    action: str
    old_value: Optional[Dict[str, Any]] = None
    new_value: Optional[Dict[str, Any]] = None
    performed_at: datetime
    remarks: Optional[str] = None


class ResourceDetailOut(BaseModel):
    resource: ResourceOut
    ledger: List[ResourceLedgerEntry]
    location_history: List[ResourceLocationEntry]
    history: List[ResourceHistoryEntry]
    quantity_leased: float
    quantity_allocated: float
    can_edit: bool


class ResourceFormOptions(BaseModel):
    owners: List[Dict[str, Any]]
    zones: List[Dict[str, Any]]
    resource_types: List[str]
    units: List[str]
    operator_statuses: List[str]
    all_statuses: List[str]
    mobility_classes: List[str]
    current_role: str
    can_manage: bool


# ---------------------------------------------------------------------------
# Emergency requests
# Allowed values mirror the CHECK constraints on emergency_requests in
# schema.sql / migrations 0004 + 0008. Keep them in sync.
# ---------------------------------------------------------------------------
RESOURCE_TYPES = ('generator', 'boat', 'medical_supply', 'shelter_capacity', 'volunteer', 'vehicle', 'other')
URGENCY_LEVELS = ('critical', 'high', 'medium', 'low')
# Mobility / accessibility requirement -> pool.mobility_class of the
# (zone x resource_type x mobility) pool the request is registered against in
# the request_pool_dependency index. 'any' = no special access requirement.
MOBILITY_CLASSES = ('any', 'land', 'boat', 'amphibious', 'air')

ResourceTypeNeeded = Literal['generator', 'boat', 'medical_supply', 'shelter_capacity', 'volunteer', 'vehicle', 'other']
UrgencyLevel = Literal['critical', 'high', 'medium', 'low']
MobilityClass = Literal['any', 'land', 'boat', 'amphibious', 'air']


class EmergencyRequestBase(BaseModel):
    resource_type_needed: str
    quantity_requested: float
    urgency_level: str
    status: str
    description: Optional[str] = None
    idempotency_key: Optional[str] = None
    source_channel: Optional[str] = None


class EmergencyRequestCreate(BaseModel):
    """Payload for POST /api/v1/requests.

    `status` is intentionally NOT accepted: the initial lifecycle state is
    defined by the database column default (emergency_requests.status).
    Location precedence: latitude/longitude > location_wkt > the zone's own
    point (zones.location).
    """
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    requester_id: UUID
    zone_id: UUID
    resource_type_needed: ResourceTypeNeeded
    # NUMERIC(10,2) CHECK (quantity_requested > 0)
    quantity_requested: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    urgency_level: UrgencyLevel
    mobility_requirement: MobilityClass = 'any'
    description: Optional[str] = Field(default=None, max_length=1000)
    needed_by: Optional[datetime] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    location_wkt: Optional[str] = Field(default=None, max_length=200)
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=100)
    source_channel: Optional[str] = Field(default=None, max_length=50)

    @field_validator('description', 'source_channel', 'location_wkt', 'idempotency_key')
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and v == '':
            return None
        return v

    @field_validator('needed_by')
    @classmethod
    def _needed_by_in_future(cls, v):
        if v is None:
            return v
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError('needed_by must be in the future')
        return v

    @model_validator(mode='after')
    def _lat_lng_together(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('latitude and longitude must be provided together')
        return self


class EmergencyRequestOut(EmergencyRequestBase):
    request_id: UUID
    requester_id: UUID
    zone_id: UUID
    quantity_fulfilled: float
    needed_by: Optional[datetime] = None
    requested_at: datetime
    created_at: datetime
    updated_at: datetime
    zone_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Request Status Tracking (derived from the database; see services/request_tracking.py)
    tracking_stage: Optional[str] = None          # pending | matching | partially_fulfilled | fulfilled | cancelled | expired
    quantity_remaining: Optional[float] = None
    quantity_reserved: Optional[float] = None     # active, unexpired leased reservations
    quantity_in_progress: Optional[float] = None  # allocations not yet confirmed
    matching_active: Optional[bool] = None
    model_config = ConfigDict(from_attributes=True)


class PoolDependencyOut(BaseModel):
    pool_id: UUID
    zone_id: UUID
    resource_type: str
    mobility_class: str


class EmergencyRequestCreatedOut(EmergencyRequestOut):
    pool_dependency: Optional[PoolDependencyOut] = None
    event_outbox_id: Optional[UUID] = None
    idempotent_replay: bool = False


class RequesterOption(BaseModel):
    requester_id: UUID
    name: str
    requester_type: str
    verified_flag: bool


class ZoneOption(BaseModel):
    zone_id: UUID
    zone_name: str
    zone_type: str
    risk_level: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class RequestFormOptions(BaseModel):
    requesters: List[RequesterOption]
    zones: List[ZoneOption]
    resource_types: List[str]
    urgency_levels: List[str]
    mobility_classes: List[str]
    current_role: str

class TrackingStep(BaseModel):
    key: str
    label: str
    state: Literal['complete', 'current', 'upcoming', 'skipped']


class TrackingQuantities(BaseModel):
    requested: float
    fulfilled: float
    remaining: float
    reserved: float
    in_progress: float


class TrackingReservation(BaseModel):
    reservation_id: UUID
    resource_id: UUID
    resource_type: str
    resource_subtype: Optional[str] = None
    unit_of_measure: Optional[str] = None
    owner_name: Optional[str] = None
    quantity: float
    status: str
    lease_expires_at: datetime
    lease_active: bool
    priority_snapshot: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    allocation_id: Optional[UUID] = None          # set once the lease was converted (migration 0012)
    final_score: Optional[float] = None           # from matching_decision
    score_components: Optional[Dict[str, Any]] = None
    match_mode: Optional[str] = None


class TrackingAllocation(BaseModel):
    allocation_id: UUID
    resource_id: UUID
    resource_type: str
    resource_subtype: Optional[str] = None
    unit_of_measure: Optional[str] = None
    owner_name: Optional[str] = None
    quantity_allocated: float
    allocation_status: str
    distance_km: Optional[float] = None
    matched_at: datetime
    dispatched_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    reservation_id: Optional[UUID] = None
    priority_score: Optional[float] = None
    notes: Optional[str] = None


class TrackingEvent(BaseModel):
    at: datetime
    kind: str
    label: str
    detail: Optional[str] = None


class RequestTrackingOut(BaseModel):
    request: EmergencyRequestOut
    stage: str
    db_status: str
    is_terminal: bool
    steps: List[TrackingStep]
    quantities: TrackingQuantities
    reservations: List[TrackingReservation]
    allocations: List[TrackingAllocation]
    timeline: List[TrackingEvent]
    last_change_at: datetime
    as_of: datetime
    quantity_to_cover: float = 0          # requested - fulfilled - reserved - in progress
    viewer_role: str = 'coordinator'
    can_manage: bool = False              # coordinator: may match / allocate / dispatch / confirm


class AllocateReservationIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    notes: Optional[str] = Field(default=None, max_length=500)


class AllocationTransitionIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    status: Literal['dispatched', 'in_transit', 'delivered', 'confirmed', 'cancelled']
    notes: Optional[str] = Field(default=None, max_length=500)


class AllocationRowOut(BaseModel):
    allocation_id: UUID
    request_id: UUID
    resource_id: UUID
    reservation_id: Optional[UUID] = None
    quantity_allocated: float
    allocation_status: str
    distance_km: Optional[float] = None
    priority_score: Optional[float] = None
    matched_at: datetime
    dispatched_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    notes: Optional[str] = None
    request_status: str
    quantity_requested: float
    quantity_fulfilled: float


class AllocationActionOut(BaseModel):
    allocation: AllocationRowOut
    previous_status: Optional[str] = None
    event_outbox_id: Optional[UUID] = None


class ReservationReleaseOut(BaseModel):
    reservation_id: UUID
    status: str
    event_outbox_id: Optional[UUID] = None


class MatchCandidateOut(BaseModel):
    resource_id: UUID
    resource_type: str
    resource_subtype: Optional[str] = None
    owner_id: UUID
    quantity_available: float
    unit_of_measure: str
    distance_km: float
    score: float
    score_components: Dict[str, Any]


class MatchCandidatesOut(BaseModel):
    request_id: UUID
    request_status: str
    quantity_requested: float
    quantity_fulfilled: float
    quantity_committed: float
    quantity_to_cover: float
    max_distance_km: float
    candidates: List[MatchCandidateOut]


# ---------------------------------------------------------------------------
# Authentication (migration 0015: app_users + SECURITY DEFINER auth functions)
# ---------------------------------------------------------------------------
AppRoleLiteral = Literal['requester', 'owner', 'coordinator']


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)
    # The role the user chose on the sign-in screen. It never grants anything:
    # the token's role always comes from the account; a mismatch is refused.
    expected_role: Optional[AppRoleLiteral] = None


class RegisterRequest(BaseModel):
    """Public sign-up. `role` 'coordinator' is accepted only so the API can
    answer with a clear 403; coordinator accounts are never self-created."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    role: AppRoleLiteral
    username: str = Field(..., min_length=3, max_length=64, pattern=r'^[A-Za-z0-9._-]+$')
    password: str = Field(..., min_length=10, max_length=256)
    display_name: str = Field(..., min_length=2, max_length=150)
    contact_phone: str = Field(..., min_length=6, max_length=20, pattern=r'^\+?[0-9][0-9 ()-]{4,18}[0-9]$')
    contact_email: Optional[str] = Field(default=None, max_length=150,
                                         pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    owner_type: Optional[Literal['government', 'ngo', 'private', 'community']] = None

    @field_validator('username')
    @classmethod
    def _lower_username(cls, v: str) -> str:
        return v.lower()

    @field_validator('contact_email', mode='before')
    @classmethod
    def _blank_email_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode='after')
    def _checks(self):
        if self.password.lower() == self.username.lower():
            raise ValueError('password must not be the same as the username')
        if not (any(c.isalpha() for c in self.password) and any(c.isdigit() for c in self.password)):
            raise ValueError('password must contain at least one letter and one digit')
        if self.role == 'owner' and self.owner_type is None:
            raise ValueError('owner_type is required for a resource owner account')
        if self.role != 'owner' and self.owner_type is not None:
            raise ValueError('owner_type applies only to resource owner accounts')
        return self


class RegisterResponse(BaseModel):
    user_id: UUID
    username: str
    role: AppRoleLiteral
    status: Literal['active', 'pending_approval']
    message: str


class AuthUserOut(BaseModel):
    user_id: UUID                 # app_users.user_id
    subject_id: UUID              # requester_id / owner_id / system_users.user_id
    role: AppRoleLiteral
    display_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal['bearer'] = 'bearer'
    expires_in: int               # seconds
    user: AuthUserOut


class TokenData(BaseModel):
    """Identity of an authenticated caller (validated JWT + active account)."""
    sub: str                      # subject entity id (requester / owner / system user)
    role: AppRoleLiteral
    user_id: Optional[str] = None # app_users.user_id
    name: Optional[str] = None


# ---------------------------------------------------------------------------
# Requester profiles (contact details are private)
# ---------------------------------------------------------------------------
class RequesterProfileOut(BaseModel):
    requester_id: UUID
    name: str
    requester_type: str
    verified_flag: bool
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_masked: bool          # true -> contact_* are masked, not the real values


class RequesterContactUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    contact_phone: Optional[str] = Field(default=None, min_length=5, max_length=20, pattern=r"^\+?[0-9][0-9 ()-]{3,19}$")
    contact_email: Optional[str] = Field(default=None, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @model_validator(mode='after')
    def _at_least_one(self):
        if self.contact_phone is None and self.contact_email is None:
            raise ValueError("Provide contact_phone and/or contact_email.")
        return self
