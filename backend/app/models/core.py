import uuid
from sqlalchemy import Column, String, Integer, Numeric, Boolean, Text, ForeignKey, DateTime, func, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from app.models.base import Base

class Owner(Base):
    __tablename__ = 'owners'
    owner_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    owner_type = Column(String(20), nullable=False)
    contact_phone = Column(String(20), nullable=False)
    contact_email = Column(String(150))
    verification_status = Column(String(20), nullable=False, default='pending')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class SystemUser(Base):
    __tablename__ = 'system_users'
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    role = Column(String(20), nullable=False)
    agency_affiliation = Column(String(150))
    contact_info = Column(String(150))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class Zone(Base):
    __tablename__ = 'zones'
    zone_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_name = Column(String(150), nullable=False)
    zone_type = Column(String(20), nullable=False)
    parent_zone_id = Column(UUID(as_uuid=True), ForeignKey('zones.zone_id'))
    location = Column(Geography('POINT', srid=4326), nullable=False)
    risk_level = Column(String(10), nullable=False, default='medium')
    population_estimate = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class Shelter(Base):
    __tablename__ = 'shelters'
    shelter_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_id = Column(UUID(as_uuid=True), ForeignKey('zones.zone_id'), nullable=False)
    name = Column(String(150), nullable=False)
    location = Column(Geography('POINT', srid=4326))
    capacity_total = Column(Integer, nullable=False)
    capacity_occupied = Column(Integer, nullable=False, default=0)
    status = Column(String(10), nullable=False, default='open')
    contact_person = Column(String(150))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class Resource(Base):
    __tablename__ = 'resources'
    resource_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey('owners.owner_id'), nullable=False)
    current_zone_id = Column(UUID(as_uuid=True), ForeignKey('zones.zone_id'), nullable=False)
    resource_type = Column(String(20), nullable=False)
    resource_subtype = Column(String(100))
    quantity_total = Column(Numeric(10,2), nullable=False)
    quantity_available = Column(Numeric(10,2), nullable=False)
    unit_of_measure = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default='available')
    location = Column(Geography('POINT', srid=4326), nullable=False)
    condition_notes = Column(Text)
    last_verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    capabilities = Column(JSONB)

class Requester(Base):
    __tablename__ = 'requesters'
    requester_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    requester_type = Column(String(20), nullable=False)
    contact_phone = Column(String(20), nullable=False)
    contact_email = Column(String(150))
    verified_flag = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class EmergencyRequest(Base):
    __tablename__ = 'emergency_requests'
    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requester_id = Column(UUID(as_uuid=True), ForeignKey('requesters.requester_id'), nullable=False)
    zone_id = Column(UUID(as_uuid=True), ForeignKey('zones.zone_id'), nullable=False)
    duplicate_of_request_id = Column(UUID(as_uuid=True), ForeignKey('emergency_requests.request_id'))
    resource_type_needed = Column(String(20), nullable=False)
    quantity_requested = Column(Numeric(10,2), nullable=False)
    quantity_fulfilled = Column(Numeric(10,2), nullable=False, default=0)
    urgency_level = Column(String(10), nullable=False)
    # Initial lifecycle state is defined by the database column default
    # (DEFAULT 'open' in schema.sql / migration 0004); no Python-side default,
    # so an INSERT that omits status always gets the database-defined value.
    status = Column(String(20), nullable=False, server_default=text("'open'"))
    description = Column(Text)
    location = Column(Geography('POINT', srid=4326), nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    needed_by = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    idempotency_key = Column(String(100), unique=True)
    source_channel = Column(String(50))

class Allocation(Base):
    __tablename__ = 'allocations'
    allocation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey('emergency_requests.request_id'), nullable=False)
    resource_id = Column(UUID(as_uuid=True), ForeignKey('resources.resource_id'), nullable=False)
    matched_by = Column(UUID(as_uuid=True), ForeignKey('system_users.user_id'))
    quantity_allocated = Column(Numeric(10,2), nullable=False)
    allocation_status = Column(String(20), nullable=False, default='matched')
    distance_km = Column(Numeric(6,2))
    priority_score = Column(Numeric(5,2))
    matched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    dispatched_at = Column(DateTime(timezone=True))
    confirmed_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    # Leased reservation this allocation was converted from (migration 0012, UNIQUE).
    reservation_id = Column(UUID(as_uuid=True), ForeignKey('reservation.reservation_id'))

class Reservation(Base):
    __tablename__ = 'reservation'
    reservation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey('emergency_requests.request_id'), nullable=False)
    resource_id = Column(UUID(as_uuid=True), ForeignKey('resources.resource_id'), nullable=False)
    quantity = Column(Numeric(10,2), nullable=False)
    status = Column(String(20), nullable=False, default='active')
    lease_expires_at = Column(DateTime(timezone=True), nullable=False)
    priority_snapshot = Column(Numeric(5,2))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class EventOutbox(Base):
    __tablename__ = 'event_outbox'
    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False)
    pool_id = Column(UUID(as_uuid=True))
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    # Outcome of processing (affected pools / requests, leases, timing) — migration 0014.
    processing_result = Column(JSONB)

class Pool(Base):
    __tablename__ = 'pool'
    pool_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_id = Column(UUID(as_uuid=True), ForeignKey('zones.zone_id'), nullable=False)
    resource_type = Column(String(20), nullable=False)
    mobility_class = Column(String(20))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class RequestPoolDependency(Base):
    __tablename__ = 'request_pool_dependency'
    dependency_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey('emergency_requests.request_id'), nullable=False)
    pool_id = Column(UUID(as_uuid=True), ForeignKey('pool.pool_id'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class MatchingDecision(Base):
    __tablename__ = 'matching_decision'
    decision_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey('emergency_requests.request_id'), nullable=False)
    resource_id = Column(UUID(as_uuid=True), ForeignKey('resources.resource_id'), nullable=False)
    score_components = Column(JSONB)
    final_score = Column(Numeric(10,4))
    algorithm_version = Column(String(50))
    mode = Column(String(20))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class HazardArea(Base):
    __tablename__ = 'hazard_area'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    geometry = Column(Geography('MULTIPOLYGON', srid=4326), nullable=False)
    hazard_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class ResourceLocationHistory(Base):
    __tablename__ = 'resource_location_history'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id = Column(UUID(as_uuid=True), ForeignKey('resources.resource_id'), nullable=False)
    location = Column(Geography('POINT', srid=4326), nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source = Column(String(50))
    confidence = Column(Numeric(5,2))

class ResourceLedger(Base):
    __tablename__ = 'resource_ledger'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id = Column(UUID(as_uuid=True), ForeignKey('resources.resource_id'), nullable=False)
    delta_qty = Column(Numeric(10,2), nullable=False)
    reason = Column(String(50), nullable=False)
    ref_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

