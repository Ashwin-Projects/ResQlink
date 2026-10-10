-- ============================================================================
-- ResQLink — Consolidated Schema (PostgreSQL 14+, PostGIS 3+)
-- This file is the flattened equivalent of running all Alembic migrations
-- in migrations/versions/ in order. Use it for a fast one-shot local setup;
-- use Alembic for versioned, incremental, re-runnable deployment.
-- Sections 1-6 = migrations 0001-0007, section 7 = 0008 (Phase 2b),
-- section 8 = 0009 (RLS), section 9 = 0010 (request-creation audit/grants),
-- section 10 = 0011 (request status guard + status-change audit),
-- section 11 = 0012 (reservation -> allocation link + reservation audit),
-- section 12 = 0013 (resource audit / ledger / location history),
-- section 13 = 0014 (lease revocation functions + event_outbox.processing_result),
-- section 14 = 0015 (login role, app_users + auth functions, least-privilege grants / RLS).
-- docker-compose.yml initialises the database from this file, so it MUST stay
-- in sync with migrations/versions/.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. EXTENSIONS
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS postgis;    -- geography type + GiST + ST_* / <->

-- ----------------------------------------------------------------------------
-- 1. REFERENCE / MASTER DATA: owners, system_users, zones
-- ----------------------------------------------------------------------------

CREATE TABLE owners (
    owner_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(150) NOT NULL,
    owner_type           VARCHAR(20)  NOT NULL
                          CHECK (owner_type IN ('government','ngo','private','community')),
    contact_phone        VARCHAR(20)  NOT NULL,
    contact_email        VARCHAR(150),
    verification_status  VARCHAR(20)  NOT NULL DEFAULT 'pending'
                          CHECK (verification_status IN ('verified','pending','suspended')),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE system_users (
    user_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(150) NOT NULL,
    role                 VARCHAR(20)  NOT NULL
                          CHECK (role IN ('coordinator','dispatcher','admin','field_verifier','auditor')),
    agency_affiliation   VARCHAR(150),
    contact_info         VARCHAR(150),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE zones (
    zone_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_name            VARCHAR(150) NOT NULL,
    zone_type            VARCHAR(20)  NOT NULL
                          CHECK (zone_type IN ('district','ward','village','shelter_site')),
    parent_zone_id       UUID REFERENCES zones(zone_id) ON DELETE SET NULL,
    location             geography(Point,4326) NOT NULL,
    risk_level           VARCHAR(10)  NOT NULL DEFAULT 'medium'
                          CHECK (risk_level IN ('critical','high','medium','low')),
    population_estimate  INTEGER CHECK (population_estimate IS NULL OR population_estimate >= 0),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT zones_parent_not_self CHECK (parent_zone_id IS NULL OR parent_zone_id <> zone_id)
);

-- ----------------------------------------------------------------------------
-- 2. RESOURCES, SHELTERS, AND RESOURCE-ZONE COVERAGE (M:M)
-- ----------------------------------------------------------------------------

CREATE TABLE shelters (
    shelter_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_id              UUID NOT NULL REFERENCES zones(zone_id) ON DELETE RESTRICT,
    name                 VARCHAR(150) NOT NULL,
    location             geography(Point,4326),
    capacity_total       INTEGER NOT NULL CHECK (capacity_total >= 0),
    capacity_occupied    INTEGER NOT NULL DEFAULT 0 CHECK (capacity_occupied >= 0),
    status               VARCHAR(10) NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open','full','closed')),
    contact_person       VARCHAR(150),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT shelters_capacity_check CHECK (capacity_occupied <= capacity_total)
);

CREATE TABLE resources (
    resource_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id             UUID NOT NULL REFERENCES owners(owner_id) ON DELETE RESTRICT,
    current_zone_id      UUID NOT NULL REFERENCES zones(zone_id) ON DELETE RESTRICT,
    resource_type        VARCHAR(20) NOT NULL
                          CHECK (resource_type IN ('generator','boat','medical_supply','shelter_capacity','volunteer','vehicle','other')),
    resource_subtype     VARCHAR(100),
    quantity_total       NUMERIC(10,2) NOT NULL CHECK (quantity_total >= 0),
    quantity_available   NUMERIC(10,2) NOT NULL CHECK (quantity_available >= 0),
    unit_of_measure      VARCHAR(20) NOT NULL
                          CHECK (unit_of_measure IN ('units','liters','kits','seats','headcount','vehicles')),
    status               VARCHAR(20) NOT NULL DEFAULT 'available'
                          CHECK (status IN ('available','allocated','in_transit','depleted','maintenance','unavailable')),
    location              geography(Point,4326) NOT NULL,
    condition_notes       TEXT,
    last_verified_at      TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT resources_qty_available_le_total CHECK (quantity_available <= quantity_total)
);

CREATE TABLE resource_zone_coverage (
    coverage_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id          UUID NOT NULL REFERENCES resources(resource_id) ON DELETE CASCADE,
    zone_id              UUID NOT NULL REFERENCES zones(zone_id) ON DELETE CASCADE,
    coverage_priority    INTEGER NOT NULL DEFAULT 100 CHECK (coverage_priority >= 0),
    CONSTRAINT uq_resource_zone UNIQUE (resource_id, zone_id)
);

-- ----------------------------------------------------------------------------
-- 3. REQUESTERS AND EMERGENCY REQUESTS
-- ----------------------------------------------------------------------------

CREATE TABLE requesters (
    requester_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(150) NOT NULL,
    requester_type       VARCHAR(20) NOT NULL
                          CHECK (requester_type IN ('individual','shelter_manager','government_official','ngo_field_worker')),
    contact_phone        VARCHAR(20) NOT NULL,
    contact_email        VARCHAR(150),
    verified_flag        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE emergency_requests (
    request_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_id             UUID NOT NULL REFERENCES requesters(requester_id) ON DELETE RESTRICT,
    zone_id                  UUID NOT NULL REFERENCES zones(zone_id) ON DELETE RESTRICT,
    duplicate_of_request_id  UUID REFERENCES emergency_requests(request_id) ON DELETE SET NULL,
    resource_type_needed     VARCHAR(20) NOT NULL
                              CHECK (resource_type_needed IN ('generator','boat','medical_supply','shelter_capacity','volunteer','vehicle','other')),
    quantity_requested       NUMERIC(10,2) NOT NULL CHECK (quantity_requested > 0),
    quantity_fulfilled       NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (quantity_fulfilled >= 0),
    urgency_level            VARCHAR(10) NOT NULL
                              CHECK (urgency_level IN ('critical','high','medium','low')),
    status                   VARCHAR(20) NOT NULL DEFAULT 'open'
                              CHECK (status IN ('open','partially_fulfilled','fulfilled','cancelled','expired')),
    description               TEXT,
    location                  geography(Point,4326) NOT NULL,
    requested_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    needed_by                  TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT emergency_requests_fulfilled_le_requested CHECK (quantity_fulfilled <= quantity_requested),
    CONSTRAINT emergency_requests_not_self_duplicate CHECK (duplicate_of_request_id IS NULL OR duplicate_of_request_id <> request_id)
);

-- ----------------------------------------------------------------------------
-- 4. ALLOCATIONS (M:M junction w/ lifecycle) AND AUDIT LOG
-- ----------------------------------------------------------------------------

CREATE TABLE allocations (
    allocation_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id           UUID NOT NULL REFERENCES emergency_requests(request_id) ON DELETE RESTRICT,
    resource_id          UUID NOT NULL REFERENCES resources(resource_id) ON DELETE RESTRICT,
    matched_by           UUID REFERENCES system_users(user_id) ON DELETE SET NULL,
    quantity_allocated    NUMERIC(10,2) NOT NULL CHECK (quantity_allocated > 0),
    allocation_status     VARCHAR(20) NOT NULL DEFAULT 'matched'
                          CHECK (allocation_status IN ('matched','dispatched','in_transit','delivered','confirmed','rejected','cancelled')),
    distance_km            NUMERIC(6,2),
    priority_score          NUMERIC(5,2),
    matched_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at            TIMESTAMPTZ,
    confirmed_at             TIMESTAMPTZ,
    notes                     TEXT,
    CONSTRAINT allocations_confirmed_after_matched CHECK (confirmed_at IS NULL OR confirmed_at >= matched_at)
);

CREATE TABLE allocation_history (
    log_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type          VARCHAR(20) NOT NULL
                          CHECK (entity_type IN ('request','resource','allocation','owner')),
    entity_id            UUID NOT NULL,
    allocation_id        UUID REFERENCES allocations(allocation_id) ON DELETE SET NULL,
    action                VARCHAR(20) NOT NULL
                          CHECK (action IN ('created','status_changed','quantity_updated','matched','dispatched','confirmed','rejected','cancelled','reassigned','escalated')),
    old_value              JSONB,
    new_value               JSONB,
    performed_by             UUID REFERENCES system_users(user_id) ON DELETE SET NULL,
    performed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    remarks                    TEXT
);

-- ============================================================================
-- 5. INDEXES — matching-engine access patterns
-- ============================================================================
-- Proximity: GiST indexes on every geography column. PostGIS's GiST support
-- for `geography` accelerates both bounded-radius search (ST_DWithin, which
-- can use the index because it has an indexable "overlaps the bounding box
-- expanded by distance" clause under the hood) and true k-nearest-neighbor
-- ordering via the `<->` distance operator (`ORDER BY location <-> :point
-- LIMIT N`), which PostGIS implements as an index-ordered scan — no need to
-- compute distance to every row first. `geography` (vs. `geometry`) is used
-- so distances are correct great-circle meters without the app having to
-- pick/manage a projection, which matters when a flood/cyclone response can
-- span a wide geographic area.
CREATE INDEX idx_zones_location_gist      ON zones             USING GIST (location);
CREATE INDEX idx_shelters_location_gist   ON shelters          USING GIST (location) WHERE location IS NOT NULL;
CREATE INDEX idx_resources_location_gist  ON resources         USING GIST (location);
CREATE INDEX idx_requests_location_gist   ON emergency_requests USING GIST (location);

-- Matching engine's primary candidate-resource filter: status + type + zone.
-- Partial index (WHERE status = 'available') keeps it small — depleted/
-- maintenance/unavailable resources are never candidates, so there's no
-- reason to carry them in the index the hot-path query scans.
CREATE INDEX idx_resources_status_type_zone
    ON resources (status, resource_type, current_zone_id)
    WHERE status = 'available';

CREATE INDEX idx_resources_owner         ON resources (owner_id);
CREATE INDEX idx_resources_current_zone  ON resources (current_zone_id);

-- Resource <-> zone coverage lookups in both directions.
CREATE INDEX idx_coverage_zone      ON resource_zone_coverage (zone_id);
CREATE INDEX idx_coverage_resource  ON resource_zone_coverage (resource_id);

-- Request queue: open/partially-fulfilled requests ranked by urgency, then age.
-- Partial index again — fulfilled/cancelled/expired requests are irrelevant
-- to the live matching queue and would otherwise bloat this index over the
-- life of a multi-week disaster response.
CREATE INDEX idx_requests_open_urgency
    ON emergency_requests (urgency_level, requested_at)
    WHERE status IN ('open','partially_fulfilled');

CREATE INDEX idx_requests_requester    ON emergency_requests (requester_id);
CREATE INDEX idx_requests_zone         ON emergency_requests (zone_id);
CREATE INDEX idx_requests_duplicate_of ON emergency_requests (duplicate_of_request_id)
    WHERE duplicate_of_request_id IS NOT NULL;

-- Allocation lookups: both directions of the M:M junction, filterable by
-- status (used by the quantity-reservation triggers and dashboards alike).
CREATE INDEX idx_allocations_resource_status ON allocations (resource_id, allocation_status);
CREATE INDEX idx_allocations_request_status  ON allocations (request_id, allocation_status);
CREATE INDEX idx_allocations_matched_by      ON allocations (matched_by);

-- Audit trail reconstruction for a given entity, in chronological order.
CREATE INDEX idx_history_entity       ON allocation_history (entity_type, entity_id, performed_at);
CREATE INDEX idx_history_allocation   ON allocation_history (allocation_id);
CREATE INDEX idx_history_performed_by ON allocation_history (performed_by);

-- Zone hierarchy / shelter-to-zone traversal.
CREATE INDEX idx_zones_parent  ON zones (parent_zone_id);
CREATE INDEX idx_shelters_zone ON shelters (zone_id);

-- ============================================================================
-- 6. TRIGGERS / FUNCTIONS — business rules the CHECK constraints can't express
-- ============================================================================
-- Single-row CHECK constraints (above) enforce e.g. quantity_available >= 0
-- and quantity_available <= quantity_total. They CANNOT enforce a cross-row
-- rule like "sum of this resource's active allocations <= quantity_total" —
-- standard SQL CHECK constraints only see the row being written. That rule,
-- and the allocation state machine, are enforced here with triggers that run
-- inside the same transaction as the write, using row-level locking
-- (SELECT ... FOR UPDATE) to make concurrent allocation attempts on the same
-- resource serialize safely instead of racing (NFR8/NFR9).

-- Generic updated_at bump.
CREATE OR REPLACE FUNCTION fn_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_owners_updated_at    BEFORE UPDATE ON owners    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_shelters_updated_at  BEFORE UPDATE ON shelters  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_resources_updated_at BEFORE UPDATE ON resources FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_requests_updated_at  BEFORE UPDATE ON emergency_requests FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- Reserve resource quantity at allocation creation.
CREATE OR REPLACE FUNCTION fn_reserve_resource_quantity() RETURNS TRIGGER AS $$
DECLARE
    v_available NUMERIC(10,2);
BEGIN
    IF NEW.allocation_status IN ('matched','dispatched','in_transit','delivered','confirmed') THEN
        SELECT quantity_available INTO v_available
        FROM resources WHERE resource_id = NEW.resource_id
        FOR UPDATE;

        IF v_available IS NULL THEN
            RAISE EXCEPTION 'Resource % not found', NEW.resource_id;
        END IF;

        IF v_available < NEW.quantity_allocated THEN
            RAISE EXCEPTION 'Insufficient quantity_available (%) on resource % for requested allocation (%)',
                v_available, NEW.resource_id, NEW.quantity_allocated;
        END IF;

        UPDATE resources
        SET quantity_available = quantity_available - NEW.quantity_allocated
        WHERE resource_id = NEW.resource_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_allocations_reserve_qty
    BEFORE INSERT ON allocations
    FOR EACH ROW EXECUTE FUNCTION fn_reserve_resource_quantity();

-- Allocation state machine + quantity release / request roll-up on status change.
CREATE OR REPLACE FUNCTION fn_allocations_on_status_change() RETURNS TRIGGER AS $$
DECLARE
    v_requested NUMERIC(10,2);
    v_fulfilled NUMERIC(10,2);
BEGIN
    IF NEW.allocation_status = OLD.allocation_status THEN
        RETURN NEW;
    END IF;

    IF NOT (
        (OLD.allocation_status = 'matched'    AND NEW.allocation_status IN ('dispatched','rejected','cancelled')) OR
        (OLD.allocation_status = 'dispatched' AND NEW.allocation_status IN ('in_transit','cancelled')) OR
        (OLD.allocation_status = 'in_transit' AND NEW.allocation_status IN ('delivered','cancelled')) OR
        (OLD.allocation_status = 'delivered'  AND NEW.allocation_status = 'confirmed')
    ) THEN
        RAISE EXCEPTION 'Invalid allocation status transition: % -> %', OLD.allocation_status, NEW.allocation_status;
    END IF;

    -- Release reserved quantity if the allocation dies before confirmation.
    IF NEW.allocation_status IN ('rejected','cancelled') THEN
        UPDATE resources
        SET quantity_available = quantity_available + OLD.quantity_allocated
        WHERE resource_id = OLD.resource_id;
    END IF;

    IF NEW.allocation_status = 'dispatched' AND NEW.dispatched_at IS NULL THEN
        NEW.dispatched_at := now();
    END IF;
    IF NEW.allocation_status = 'confirmed' AND NEW.confirmed_at IS NULL THEN
        NEW.confirmed_at := now();
    END IF;

    -- On confirmation, roll the fulfilled quantity up into the parent request.
    IF NEW.allocation_status = 'confirmed' THEN
        SELECT quantity_requested, quantity_fulfilled INTO v_requested, v_fulfilled
        FROM emergency_requests WHERE request_id = NEW.request_id
        FOR UPDATE;

        v_fulfilled := v_fulfilled + NEW.quantity_allocated;

        UPDATE emergency_requests
        SET quantity_fulfilled = v_fulfilled,
            status = CASE WHEN v_fulfilled >= v_requested THEN 'fulfilled' ELSE 'partially_fulfilled' END
        WHERE request_id = NEW.request_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_allocations_status_change
    BEFORE UPDATE ON allocations
    FOR EACH ROW EXECUTE FUNCTION fn_allocations_on_status_change();

-- Cascade: cancelling a request auto-cancels its still-active allocations
-- (releasing their reserved quantity via the trigger above).
CREATE OR REPLACE FUNCTION fn_requests_cascade_cancel() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'cancelled' AND OLD.status <> 'cancelled' THEN
        UPDATE allocations
        SET allocation_status = 'cancelled'
        WHERE request_id = NEW.request_id
          AND allocation_status IN ('matched','dispatched','in_transit');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_requests_cascade_cancel
    AFTER UPDATE OF status ON emergency_requests
    FOR EACH ROW EXECUTE FUNCTION fn_requests_cascade_cancel();

-- Derived status sync: resources flip to 'depleted' / back to 'available'
-- automatically as quantity_available crosses zero, but never override an
-- operator's explicit 'maintenance' / 'unavailable' flag.
CREATE OR REPLACE FUNCTION fn_resources_sync_status() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status NOT IN ('maintenance','unavailable') THEN
        IF NEW.quantity_available = 0 THEN
            NEW.status := 'depleted';
        ELSIF NEW.status = 'depleted' AND NEW.quantity_available > 0 THEN
            NEW.status := 'available';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_resources_sync_status
    BEFORE INSERT OR UPDATE OF quantity_available ON resources
    FOR EACH ROW EXECUTE FUNCTION fn_resources_sync_status();

-- Derived status sync: shelters flip to 'full' / back to 'open' automatically,
-- but never override an explicit 'closed'.
CREATE OR REPLACE FUNCTION fn_shelters_sync_status() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status <> 'closed' THEN
        IF NEW.capacity_total > 0 AND NEW.capacity_occupied >= NEW.capacity_total THEN
            NEW.status := 'full';
        ELSIF NEW.status = 'full' AND NEW.capacity_occupied < NEW.capacity_total THEN
            NEW.status := 'open';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_shelters_sync_status
    BEFORE INSERT OR UPDATE OF capacity_occupied ON shelters
    FOR EACH ROW EXECUTE FUNCTION fn_shelters_sync_status();

-- Append-only enforcement on the audit log (NFR6): no UPDATE or DELETE, ever.
CREATE OR REPLACE FUNCTION fn_prevent_history_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'allocation_history is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_history_no_update
    BEFORE UPDATE OR DELETE ON allocation_history
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_history_mutation();

-- Auto-log every allocation create / status change into allocation_history,
-- satisfying FR15/FR16 without relying on the application layer to remember to.
CREATE OR REPLACE FUNCTION fn_log_allocation_change() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by)
        VALUES ('allocation', NEW.allocation_id, NEW.allocation_id, 'created', NULL, to_jsonb(NEW), NEW.matched_by);
    ELSIF TG_OP = 'UPDATE' AND NEW.allocation_status <> OLD.allocation_status THEN
        INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by)
        VALUES ('allocation', NEW.allocation_id, NEW.allocation_id, 'status_changed', to_jsonb(OLD), to_jsonb(NEW), NEW.matched_by);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_allocations_log_insert
    AFTER INSERT ON allocations
    FOR EACH ROW EXECUTE FUNCTION fn_log_allocation_change();

CREATE TRIGGER trg_allocations_log_update
    AFTER UPDATE ON allocations
    FOR EACH ROW EXECUTE FUNCTION fn_log_allocation_change();

-- ============================================================================
-- 7. PHASE 2b — CORE INVENTION ARCHITECTURE (mirrors migration 0008)
-- hazard_area, resource_location_history, resource_ledger, reservation
-- (leased), pool, request_pool_dependency, event_outbox, matching_decision,
-- idempotency/source metadata on emergency_requests, extended lifecycle.
-- ============================================================================
CREATE TABLE hazard_area (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            geometry geography(MultiPolygon, 4326) NOT NULL,
            hazard_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical','high','medium','low')),
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_hazard_area_geometry ON hazard_area USING GIST (geometry);
CREATE TABLE resource_location_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_id UUID NOT NULL REFERENCES resources(resource_id) ON DELETE CASCADE,
            location geography(Point, 4326) NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            source VARCHAR(50),
            confidence NUMERIC(5,2) CHECK (confidence >= 0 AND confidence <= 100)
        );
        CREATE INDEX idx_res_loc_hist_res_time ON resource_location_history (resource_id, recorded_at);
        CREATE INDEX idx_res_loc_hist_location ON resource_location_history USING GIST (location);
CREATE TABLE resource_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_id UUID NOT NULL REFERENCES resources(resource_id) ON DELETE RESTRICT,
            delta_qty NUMERIC(10,2) NOT NULL,
            reason VARCHAR(50) NOT NULL,
            ref_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_resource_ledger_res ON resource_ledger(resource_id);
CREATE TABLE reservation (
            reservation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id UUID NOT NULL REFERENCES emergency_requests(request_id) ON DELETE CASCADE,
            resource_id UUID NOT NULL REFERENCES resources(resource_id) ON DELETE CASCADE,
            quantity NUMERIC(10,2) NOT NULL CHECK (quantity > 0),
            status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'expired', 'cancelled')),
            lease_expires_at TIMESTAMPTZ NOT NULL,
            priority_snapshot NUMERIC(5,2),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_reservation_status_expires ON reservation(status, lease_expires_at);
        CREATE INDEX idx_reservation_req_res ON reservation(request_id, resource_id);

        CREATE TRIGGER trg_reservation_updated_at BEFORE UPDATE ON reservation FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE OR REPLACE FUNCTION fn_reserve_reservation_quantity() RETURNS TRIGGER AS $$
        DECLARE
            v_available NUMERIC(10,2);
        BEGIN
            IF NEW.status = 'active' THEN
                SELECT quantity_available INTO v_available
                FROM resources WHERE resource_id = NEW.resource_id
                FOR UPDATE;

                IF v_available IS NULL THEN
                    RAISE EXCEPTION 'Resource % not found', NEW.resource_id;
                END IF;

                IF v_available < NEW.quantity THEN
                    RAISE EXCEPTION 'Insufficient quantity_available (%) on resource % for reservation (%)',
                        v_available, NEW.resource_id, NEW.quantity;
                END IF;

                UPDATE resources
                SET quantity_available = quantity_available - NEW.quantity
                WHERE resource_id = NEW.resource_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_reservations_reserve_qty
            BEFORE INSERT ON reservation
            FOR EACH ROW EXECUTE FUNCTION fn_reserve_reservation_quantity();
            
        CREATE OR REPLACE FUNCTION fn_reservations_status_change() RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;
            
            IF NEW.status IN ('expired', 'cancelled') THEN
                UPDATE resources
                SET quantity_available = quantity_available + OLD.quantity
                WHERE resource_id = OLD.resource_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_reservations_status_change
            BEFORE UPDATE ON reservation
            FOR EACH ROW EXECUTE FUNCTION fn_reservations_status_change();
CREATE TABLE pool (
            pool_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            zone_id UUID NOT NULL REFERENCES zones(zone_id) ON DELETE CASCADE,
            resource_type VARCHAR(20) NOT NULL,
            mobility_class VARCHAR(20),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_pool_zone_type_mob UNIQUE (zone_id, resource_type, mobility_class)
        );

        CREATE TABLE request_pool_dependency (
            dependency_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id UUID NOT NULL REFERENCES emergency_requests(request_id) ON DELETE CASCADE,
            pool_id UUID NOT NULL REFERENCES pool(pool_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_req_pool UNIQUE (request_id, pool_id)
        );
        CREATE INDEX idx_req_pool_dep_pool ON request_pool_dependency(pool_id);
        CREATE INDEX idx_req_pool_dep_req ON request_pool_dependency(request_id);
CREATE TABLE event_outbox (
            event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type VARCHAR(100) NOT NULL,
            pool_id UUID REFERENCES pool(pool_id) ON DELETE SET NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ
        );
        CREATE INDEX idx_event_outbox_unprocessed ON event_outbox(created_at) WHERE processed_at IS NULL;
CREATE TABLE matching_decision (
            decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id UUID NOT NULL REFERENCES emergency_requests(request_id) ON DELETE CASCADE,
            resource_id UUID NOT NULL REFERENCES resources(resource_id) ON DELETE CASCADE,
            score_components JSONB,
            final_score NUMERIC(10,4),
            algorithm_version VARCHAR(50),
            mode VARCHAR(20),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_matching_decision_req ON matching_decision(request_id);
ALTER TABLE resources ADD COLUMN capabilities JSONB;
ALTER TABLE emergency_requests ADD COLUMN idempotency_key VARCHAR(100) UNIQUE;
ALTER TABLE emergency_requests ADD COLUMN source_channel VARCHAR(50);
ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_allocation_status_check;
ALTER TABLE allocations ADD CONSTRAINT allocations_allocation_status_check 
        CHECK (allocation_status IN ('pending', 'matched', 'proposed', 'reserved', 'dispatched', 'in_transit', 'delivered', 'confirmed', 'fulfilled', 'rejected', 'expired', 'cancelled', 'reassigned'));
ALTER TABLE emergency_requests DROP CONSTRAINT IF EXISTS emergency_requests_status_check;
ALTER TABLE emergency_requests ADD CONSTRAINT emergency_requests_status_check 
        CHECK (status IN ('open', 'pending', 'partially_fulfilled', 'fulfilled', 'cancelled', 'expired'));
ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_action_check;
ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_action_check
        CHECK (action IN ('created','status_changed','quantity_updated','matched','dispatched','confirmed','rejected','cancelled','reassigned','escalated','expired','proposed','reserved','fulfilled'));
CREATE OR REPLACE FUNCTION fn_allocations_on_status_change() RETURNS TRIGGER AS $$
        DECLARE
            v_requested NUMERIC(10,2);
            v_fulfilled NUMERIC(10,2);
        BEGIN
            IF NEW.allocation_status = OLD.allocation_status THEN
                RETURN NEW;
            END IF;

            IF NOT (
                (OLD.allocation_status = 'pending'    AND NEW.allocation_status IN ('matched', 'cancelled')) OR
                (OLD.allocation_status = 'matched'    AND NEW.allocation_status IN ('proposed', 'reserved', 'dispatched', 'rejected', 'cancelled')) OR
                (OLD.allocation_status = 'proposed'   AND NEW.allocation_status IN ('reserved', 'rejected', 'expired', 'cancelled')) OR
                (OLD.allocation_status = 'reserved'   AND NEW.allocation_status IN ('dispatched', 'cancelled', 'expired', 'reassigned')) OR
                (OLD.allocation_status = 'dispatched' AND NEW.allocation_status IN ('in_transit', 'delivered', 'confirmed', 'cancelled', 'reassigned')) OR
                (OLD.allocation_status = 'in_transit' AND NEW.allocation_status IN ('delivered', 'cancelled')) OR
                (OLD.allocation_status = 'delivered'  AND NEW.allocation_status IN ('confirmed', 'rejected')) OR
                (OLD.allocation_status = 'confirmed'  AND NEW.allocation_status IN ('fulfilled')) OR
                (NEW.allocation_status IN ('cancelled', 'expired', 'rejected', 'reassigned'))
            ) THEN
                RAISE EXCEPTION 'Invalid allocation status transition: % -> %', OLD.allocation_status, NEW.allocation_status;
            END IF;

            IF NEW.allocation_status IN ('rejected','cancelled','expired','reassigned') THEN
                UPDATE resources
                SET quantity_available = quantity_available + OLD.quantity_allocated
                WHERE resource_id = OLD.resource_id;
            END IF;

            IF NEW.allocation_status = 'dispatched' AND NEW.dispatched_at IS NULL THEN
                NEW.dispatched_at := now();
            END IF;
            IF NEW.allocation_status IN ('confirmed', 'fulfilled') AND NEW.confirmed_at IS NULL THEN
                NEW.confirmed_at := now();
            END IF;

            IF NEW.allocation_status = 'confirmed' THEN
                SELECT quantity_requested, quantity_fulfilled INTO v_requested, v_fulfilled
                FROM emergency_requests WHERE request_id = NEW.request_id
                FOR UPDATE;

                v_fulfilled := v_fulfilled + NEW.quantity_allocated;

                UPDATE emergency_requests
                SET quantity_fulfilled = v_fulfilled,
                    status = CASE WHEN v_fulfilled >= v_requested THEN 'fulfilled' ELSE 'partially_fulfilled' END
                WHERE request_id = NEW.request_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

-- ============================================================================
-- 8. PHASE 3 — ROW-LEVEL SECURITY ROLES & POLICIES (mirrors migration 0009)
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_coordinator') THEN CREATE ROLE api_coordinator; END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_owner') THEN CREATE ROLE api_owner; END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_requester') THEN CREATE ROLE api_requester; END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_anon') THEN CREATE ROLE api_anon; END IF; END $$;
GRANT USAGE ON SCHEMA public TO api_coordinator, api_owner, api_requester, api_anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO api_coordinator;
GRANT SELECT ON zones, shelters, hazard_area TO api_owner, api_requester, api_anon;
GRANT SELECT, INSERT, UPDATE ON resources, owners TO api_owner;
GRANT SELECT, INSERT, UPDATE ON emergency_requests, requesters TO api_requester;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO api_coordinator, api_owner, api_requester;
ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE emergency_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE requesters ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_resource_policy ON resources
        FOR ALL TO api_owner
        USING (owner_id::text = current_setting('jwt.claims.owner_id', true));
CREATE POLICY coordinator_resource_policy ON resources
        FOR ALL TO api_coordinator
        USING (true);
CREATE POLICY requester_resource_policy ON resources
        FOR SELECT TO api_requester
        USING (status = 'available');
CREATE POLICY requester_self_policy ON requesters
        FOR ALL TO api_requester
        USING (requester_id::text = current_setting('jwt.claims.requester_id', true));
CREATE POLICY coordinator_requesters_policy ON requesters
        FOR ALL TO api_coordinator
        USING (true);
CREATE POLICY requester_requests_policy ON emergency_requests
        FOR ALL TO api_requester
        USING (requester_id::text = current_setting('jwt.claims.requester_id', true));
CREATE POLICY coordinator_requests_policy ON emergency_requests
        FOR ALL TO api_coordinator
        USING (true);

-- ============================================================================
-- 9. REQUEST CREATION — audit trigger + requester grants (mirrors migration 0010)
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_log_request_created() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by, remarks)
    VALUES (
        'request', NEW.request_id, NULL, 'created', NULL,
        to_jsonb(NEW) - 'location',
        NULL,
        'Emergency request created (source: ' || COALESCE(NEW.source_channel, 'unspecified') || ')'
    );
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_requests_log_insert
    AFTER INSERT ON emergency_requests
    FOR EACH ROW EXECUTE FUNCTION fn_log_request_created();
REVOKE ALL ON FUNCTION fn_log_request_created() FROM PUBLIC;
GRANT SELECT, INSERT ON pool TO api_requester;
GRANT INSERT ON request_pool_dependency TO api_requester;
GRANT INSERT ON event_outbox TO api_requester;

-- ============================================================================
-- 10. REQUEST STATUS TRACKING — lifecycle guard + status-change audit
--     (mirrors migration 0011)
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_requests_guard_status_transition() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;

    IF NOT (
        (OLD.status = 'open'                AND NEW.status IN ('pending', 'partially_fulfilled', 'fulfilled', 'cancelled', 'expired')) OR
        (OLD.status = 'pending'             AND NEW.status IN ('open', 'partially_fulfilled', 'fulfilled', 'cancelled', 'expired')) OR
        (OLD.status = 'partially_fulfilled' AND NEW.status IN ('fulfilled', 'cancelled', 'expired'))
    ) THEN
        RAISE EXCEPTION 'Invalid emergency request status transition: % -> %', OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_requests_guard_status
    BEFORE UPDATE OF status ON emergency_requests
    FOR EACH ROW EXECUTE FUNCTION fn_requests_guard_status_transition();
CREATE OR REPLACE FUNCTION fn_log_request_status_change() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by, remarks)
        VALUES (
            'request', NEW.request_id, NULL, 'status_changed',
            jsonb_build_object('status', OLD.status, 'quantity_fulfilled', OLD.quantity_fulfilled),
            jsonb_build_object('status', NEW.status, 'quantity_fulfilled', NEW.quantity_fulfilled,
                               'quantity_requested', NEW.quantity_requested),
            NULL,
            'Request status ' || OLD.status || ' -> ' || NEW.status
        );
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_requests_log_status_change
    AFTER UPDATE OF status ON emergency_requests
    FOR EACH ROW EXECUTE FUNCTION fn_log_request_status_change();
REVOKE ALL ON FUNCTION fn_log_request_status_change() FROM PUBLIC;

-- ============================================================================
-- 11. REQUEST -> MATCH -> RESERVE -> ALLOCATE workflow
--     exactly-once reservation conversion + reservation audit (mirrors migration 0012)
-- ============================================================================
ALTER TABLE allocations
    ADD COLUMN reservation_id UUID REFERENCES reservation(reservation_id) ON DELETE SET NULL;
CREATE UNIQUE INDEX uq_allocations_reservation
    ON allocations (reservation_id) WHERE reservation_id IS NOT NULL;
ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_entity_type_check;
ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_entity_type_check
    CHECK (entity_type IN ('request','resource','allocation','owner','reservation'));
CREATE OR REPLACE FUNCTION fn_log_reservation_change() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by, remarks)
        VALUES ('reservation', NEW.reservation_id, NULL, 'created', NULL, to_jsonb(NEW), NULL,
                'Lease ' || NEW.quantity || ' of resource ' || NEW.resource_id || ' for request ' || NEW.request_id);
    ELSIF TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by, remarks)
        VALUES ('reservation', NEW.reservation_id, NULL, 'status_changed',
                jsonb_build_object('status', OLD.status), to_jsonb(NEW), NULL,
                'Reservation ' || OLD.status || ' -> ' || NEW.status);
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_reservation_audit
    AFTER INSERT OR UPDATE OF status ON reservation
    FOR EACH ROW EXECUTE FUNCTION fn_log_reservation_change();
REVOKE ALL ON FUNCTION fn_log_reservation_change() FROM PUBLIC;
CREATE INDEX idx_reservation_request_status ON reservation (request_id, status);

-- ============================================================================
-- 12. RESOURCE MANAGEMENT — operator-change audit, ledger, location history
--     (mirrors migration 0013)
-- ============================================================================
ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_action_check;
ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_action_check
    CHECK (action IN ('created','status_changed','quantity_updated','matched','dispatched','confirmed','rejected',
                      'cancelled','reassigned','escalated','expired','proposed','reserved','fulfilled','updated'));
CREATE OR REPLACE FUNCTION fn_log_resource_change() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_old JSONB;
    v_new JSONB;
    v_action VARCHAR(20);
    v_location_changed BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by, remarks)
        VALUES ('resource', NEW.resource_id, NULL, 'created', NULL, to_jsonb(NEW) - 'location', NULL,
                'Resource registered: ' || NEW.quantity_total || ' ' || NEW.unit_of_measure || ' of ' || NEW.resource_type);
        INSERT INTO resource_ledger (resource_id, delta_qty, reason, ref_id)
        VALUES (NEW.resource_id, NEW.quantity_total, 'initial_stock', NULL);
        INSERT INTO resource_location_history (resource_id, location, source, confidence)
        VALUES (NEW.resource_id, NEW.location, 'operator', 100);
        RETURN NEW;
    END IF;

    v_location_changed := NEW.location::text IS DISTINCT FROM OLD.location::text;

    SELECT jsonb_object_agg(n.key, o.value), jsonb_object_agg(n.key, n.value)
      INTO v_old, v_new
    FROM jsonb_each(to_jsonb(NEW) - 'location' - 'updated_at') n
    JOIN jsonb_each(to_jsonb(OLD) - 'location' - 'updated_at') o USING (key)
    WHERE n.value IS DISTINCT FROM o.value;

    IF v_location_changed THEN
        v_old := COALESCE(v_old, '{}'::jsonb) || jsonb_build_object('location_changed', true);
        v_new := COALESCE(v_new, '{}'::jsonb) || jsonb_build_object('location_changed', true);
    END IF;

    IF v_new IS NULL THEN
        RETURN NEW;   -- nothing actually changed
    END IF;

    v_action := CASE
        WHEN NEW.status IS DISTINCT FROM OLD.status THEN 'status_changed'
        WHEN NEW.quantity_total IS DISTINCT FROM OLD.quantity_total
          OR NEW.quantity_available IS DISTINCT FROM OLD.quantity_available THEN 'quantity_updated'
        ELSE 'updated'
    END;

    INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by, remarks)
    VALUES ('resource', NEW.resource_id, NULL, v_action, v_old, v_new, NULL,
            'Resource ' || v_action || ': ' || array_to_string(ARRAY(SELECT jsonb_object_keys(v_new) ORDER BY 1), ', '));

    IF NEW.quantity_total IS DISTINCT FROM OLD.quantity_total THEN
        INSERT INTO resource_ledger (resource_id, delta_qty, reason, ref_id)
        VALUES (NEW.resource_id, NEW.quantity_total - OLD.quantity_total, 'stock_adjustment', NULL);
    END IF;

    IF v_location_changed THEN
        INSERT INTO resource_location_history (resource_id, location, source, confidence)
        VALUES (NEW.resource_id, NEW.location, 'operator', 100);
    END IF;

    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_resources_log_insert
    AFTER INSERT ON resources
    FOR EACH ROW EXECUTE FUNCTION fn_log_resource_change();
CREATE TRIGGER trg_resources_log_update
    AFTER UPDATE OF quantity_total, status, current_zone_id, location, capabilities,
                    resource_subtype, condition_notes, last_verified_at ON resources
    FOR EACH ROW EXECUTE FUNCTION fn_log_resource_change();
REVOKE ALL ON FUNCTION fn_log_resource_change() FROM PUBLIC;
GRANT INSERT ON event_outbox TO api_owner;

-- ============================================================================
-- 13. RESOURCE CHANGE -> INCREMENTAL RE-MATCHING: lease revocation functions +
--     persisted outbox processing outcome (mirrors migration 0014)
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_assert_resource_manager(p_resource_id UUID) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_role TEXT := current_setting('role', true);
BEGIN
    IF v_role = 'api_owner' THEN
        IF NOT EXISTS (SELECT 1 FROM resources
                       WHERE resource_id = p_resource_id
                         AND owner_id::text = current_setting('jwt.claims.owner_id', true)) THEN
            RAISE EXCEPTION 'resource % is not owned by the calling owner', p_resource_id
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    ELSIF v_role IS DISTINCT FROM 'api_coordinator' AND v_role IS DISTINCT FROM 'none' THEN
        RAISE EXCEPTION 'role % may not manage resource leases', v_role USING ERRCODE = 'insufficient_privilege';
    END IF;
END;
$$;
CREATE OR REPLACE FUNCTION fn_lock_resource_leases(p_resource_id UUID)
RETURNS TABLE (reservation_id UUID, request_id UUID, quantity NUMERIC, priority_snapshot NUMERIC, created_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    PERFORM fn_assert_resource_manager(p_resource_id);
    RETURN QUERY
        SELECT v.reservation_id, v.request_id, v.quantity, v.priority_snapshot, v.created_at
        FROM reservation v
        WHERE v.resource_id = p_resource_id AND v.status = 'active'
        ORDER BY v.priority_snapshot ASC NULLS FIRST, v.created_at DESC
        FOR UPDATE OF v NOWAIT;
END;
$$;
CREATE OR REPLACE FUNCTION fn_revoke_resource_leases(p_resource_id UUID, p_reservation_ids UUID[])
RETURNS TABLE (reservation_id UUID, request_id UUID, quantity NUMERIC)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    PERFORM fn_assert_resource_manager(p_resource_id);
    RETURN QUERY
        UPDATE reservation v SET status = 'cancelled'
        WHERE v.resource_id = p_resource_id
          AND v.reservation_id = ANY(p_reservation_ids)
          AND v.status = 'active'
        RETURNING v.reservation_id, v.request_id, v.quantity;
END;
$$;
REVOKE ALL ON FUNCTION fn_assert_resource_manager(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION fn_lock_resource_leases(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION fn_revoke_resource_leases(UUID, UUID[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_lock_resource_leases(UUID) TO api_coordinator, api_owner;
GRANT EXECUTE ON FUNCTION fn_revoke_resource_leases(UUID, UUID[]) TO api_coordinator, api_owner;
ALTER TABLE event_outbox ADD COLUMN processing_result JSONB;
CREATE INDEX idx_event_outbox_processed_results
    ON event_outbox (processed_at DESC) WHERE processing_result IS NOT NULL;

-- ============================================================================
-- 14. AUTHENTICATION + DATABASE-LEVEL SECURITY HARDENING (mirrors migration 0015)
--     resqlink_app login role (password set at deploy time), api_service /
--     api_auth roles, app_users + SECURITY DEFINER auth functions, least-privilege
--     REVOKE/GRANT, RLS on owners, append-only ledgers.
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_service') THEN
        CREATE ROLE api_service NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_auth') THEN
        CREATE ROLE api_auth NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'resqlink_app') THEN
        CREATE ROLE resqlink_app NOLOGIN;
    END IF;
END
$$;
ALTER ROLE resqlink_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS NOREPLICATION;
ALTER ROLE api_coordinator NOLOGIN NOBYPASSRLS;
ALTER ROLE api_owner       NOLOGIN NOBYPASSRLS;
ALTER ROLE api_requester   NOLOGIN NOBYPASSRLS;
ALTER ROLE api_service     NOLOGIN NOBYPASSRLS;
ALTER ROLE api_auth        NOLOGIN NOBYPASSRLS;
ALTER ROLE api_anon        NOLOGIN NOBYPASSRLS;
GRANT api_coordinator, api_owner, api_requester, api_service, api_auth TO resqlink_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO api_coordinator, api_owner, api_requester, api_service, api_auth;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM api_anon;
REVOKE USAGE ON SCHEMA public FROM api_anon;
CREATE TABLE app_users (
    user_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username         VARCHAR(64)  NOT NULL CHECK (username ~ '^[a-z0-9._-]{3,64}$'),
    password_hash    TEXT         NOT NULL CHECK (password_hash LIKE 'pbkdf2_sha256$%'),
    role             VARCHAR(20)  NOT NULL CHECK (role IN ('requester', 'owner', 'coordinator')),
    requester_id     UUID REFERENCES requesters(requester_id),
    owner_id         UUID REFERENCES owners(owner_id),
    system_user_id   UUID REFERENCES system_users(user_id),
    display_name     VARCHAR(150) NOT NULL,
    is_active        BOOLEAN      NOT NULL DEFAULT true,
    failed_attempts  INTEGER      NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until     TIMESTAMPTZ,
    last_login_at    TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT app_users_role_subject CHECK (
        (role = 'requester'   AND requester_id   IS NOT NULL AND owner_id IS NULL AND system_user_id IS NULL) OR
        (role = 'owner'       AND owner_id       IS NOT NULL AND requester_id IS NULL AND system_user_id IS NULL) OR
        (role = 'coordinator' AND system_user_id IS NOT NULL AND requester_id IS NULL AND owner_id IS NULL)
    )
);
CREATE UNIQUE INDEX uq_app_users_username ON app_users (lower(username));
CREATE TRIGGER trg_app_users_updated_at BEFORE UPDATE ON app_users
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
ALTER TABLE app_users ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app_users FROM PUBLIC, api_coordinator, api_owner, api_requester, api_service, api_auth, api_anon, resqlink_app;
CREATE OR REPLACE FUNCTION fn_auth_credentials(p_username TEXT)
RETURNS TABLE (user_id UUID, password_hash TEXT, role VARCHAR, subject_id UUID,
               display_name VARCHAR, is_active BOOLEAN, locked_until TIMESTAMPTZ)
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT u.user_id, u.password_hash, u.role,
           COALESCE(u.requester_id, u.owner_id, u.system_user_id),
           u.display_name, u.is_active, u.locked_until
    FROM app_users u
    WHERE lower(u.username) = lower(p_username);
$$;
CREATE OR REPLACE FUNCTION fn_auth_record_login(p_user_id UUID, p_success BOOLEAN)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_failed INTEGER;
    v_locked TIMESTAMPTZ;
BEGIN
    SELECT u.failed_attempts, u.locked_until INTO v_failed, v_locked
    FROM app_users u WHERE u.user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF p_success THEN
        UPDATE app_users SET failed_attempts = 0, locked_until = NULL, last_login_at = now()
        WHERE app_users.user_id = p_user_id;
        RETURN;
    END IF;
    -- An expired lock starts a fresh window of attempts.
    IF v_locked IS NOT NULL AND v_locked <= now() THEN
        v_failed := 0;
        v_locked := NULL;
    END IF;
    v_failed := v_failed + 1;
    IF v_failed >= 5 THEN
        v_locked := now() + interval '15 minutes';
    END IF;
    UPDATE app_users SET failed_attempts = v_failed, locked_until = v_locked
    WHERE app_users.user_id = p_user_id;
END;
$$;
CREATE OR REPLACE FUNCTION fn_auth_session(p_user_id UUID, p_role TEXT, p_subject_id UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM app_users u
        WHERE u.user_id = p_user_id
          AND u.is_active
          AND u.role = p_role
          AND COALESCE(u.requester_id, u.owner_id, u.system_user_id) = p_subject_id
    );
$$;
REVOKE ALL ON FUNCTION fn_auth_credentials(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_auth_credentials(TEXT) TO api_auth;
REVOKE ALL ON FUNCTION fn_auth_record_login(UUID, BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_auth_record_login(UUID, BOOLEAN) TO api_auth;
REVOKE ALL ON FUNCTION fn_auth_session(UUID, TEXT, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_auth_session(UUID, TEXT, UUID) TO api_auth;
CREATE OR REPLACE FUNCTION fn_log_allocation_change() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by)
        VALUES ('allocation', NEW.allocation_id, NEW.allocation_id, 'created', NULL, to_jsonb(NEW), NEW.matched_by);
    ELSIF TG_OP = 'UPDATE' AND NEW.allocation_status <> OLD.allocation_status THEN
        INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by)
        VALUES ('allocation', NEW.allocation_id, NEW.allocation_id, 'status_changed', to_jsonb(OLD), to_jsonb(NEW), NEW.matched_by);
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION fn_log_allocation_change() FROM PUBLIC;
CREATE OR REPLACE FUNCTION fn_prevent_append_only_mutation() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not permitted', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
CREATE TRIGGER trg_resource_ledger_append_only BEFORE UPDATE OR DELETE ON resource_ledger
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_append_only_mutation();
CREATE TRIGGER trg_resource_ledger_no_truncate BEFORE TRUNCATE ON resource_ledger
    FOR EACH STATEMENT EXECUTE FUNCTION fn_prevent_append_only_mutation();
CREATE TRIGGER trg_location_history_append_only BEFORE UPDATE OR DELETE ON resource_location_history
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_append_only_mutation();
CREATE TRIGGER trg_location_history_no_truncate BEFORE TRUNCATE ON resource_location_history
    FOR EACH STATEMENT EXECUTE FUNCTION fn_prevent_append_only_mutation();
CREATE TRIGGER trg_history_no_truncate BEFORE TRUNCATE ON allocation_history
    FOR EACH STATEMENT EXECUTE FUNCTION fn_prevent_append_only_mutation();
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM api_coordinator;
GRANT SELECT ON zones, owners, system_users, shelters, hazard_area,
                resources, resource_zone_coverage, resource_ledger, resource_location_history,
                requesters, emergency_requests, pool, request_pool_dependency,
                reservation, allocations, allocation_history, matching_decision, event_outbox
    TO api_coordinator;
GRANT INSERT, UPDATE ON resources, emergency_requests, reservation, allocations TO api_coordinator;
GRANT INSERT ON pool, request_pool_dependency, event_outbox, matching_decision TO api_coordinator;
ALTER TABLE owners ENABLE ROW LEVEL SECURITY;
CREATE POLICY coordinator_owners_policy ON owners FOR SELECT TO api_coordinator USING (true);
REVOKE UPDATE, DELETE, TRUNCATE ON emergency_requests FROM api_requester;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON requesters FROM api_requester;
GRANT UPDATE (contact_phone, contact_email) ON requesters TO api_requester;
GRANT SELECT (resource_id, current_zone_id, resource_type, resource_subtype, quantity_total,
              quantity_available, unit_of_measure, status, location)
    ON resources TO api_requester;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON owners FROM api_owner;
REVOKE DELETE, TRUNCATE ON resources FROM api_owner;
CREATE POLICY owner_self_policy ON owners FOR SELECT TO api_owner
    USING (owner_id::text = current_setting('jwt.claims.owner_id', true));
GRANT SELECT ON zones, system_users, shelters, hazard_area,
                resources, resource_zone_coverage, resource_ledger, resource_location_history,
                emergency_requests, pool, request_pool_dependency,
                reservation, allocations, allocation_history, matching_decision, event_outbox
    TO api_service;
GRANT SELECT (owner_id, name, owner_type, verification_status) ON owners TO api_service;
GRANT SELECT (requester_id, name, requester_type, verified_flag, created_at) ON requesters TO api_service;
GRANT INSERT ON reservation, matching_decision, event_outbox TO api_service;
GRANT UPDATE ON resources, emergency_requests, reservation, allocations, event_outbox TO api_service;
CREATE POLICY service_resources_policy  ON resources          FOR ALL    TO api_service USING (true);
CREATE POLICY service_requests_policy   ON emergency_requests FOR ALL    TO api_service USING (true);
CREATE POLICY service_requesters_policy ON requesters         FOR SELECT TO api_service USING (true);
CREATE POLICY service_owners_policy     ON owners             FOR SELECT TO api_service USING (true);
CREATE OR REPLACE FUNCTION fn_assert_resource_manager(p_resource_id UUID) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_role TEXT := current_setting('role', true);
BEGIN
    IF v_role = 'api_owner' THEN
        IF NOT EXISTS (SELECT 1 FROM resources
                       WHERE resource_id = p_resource_id
                         AND owner_id::text = current_setting('jwt.claims.owner_id', true)) THEN
            RAISE EXCEPTION 'resource % is not owned by the calling owner', p_resource_id
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    ELSIF v_role IS DISTINCT FROM 'api_coordinator' THEN
        RAISE EXCEPTION 'role % may not manage resource leases', COALESCE(v_role, 'none')
            USING ERRCODE = 'insufficient_privilege';
    END IF;
END;
$$;
REVOKE ALL ON FUNCTION fn_assert_resource_manager(UUID) FROM PUBLIC;
