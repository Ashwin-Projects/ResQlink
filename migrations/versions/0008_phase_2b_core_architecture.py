"""Phase 2b core architecture

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # A. SPATIAL EXTENSION - hazard_area
    op.execute("""
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
    """)

    # B. TEMPORAL RESOURCE LOCATION - resource_location_history
    op.execute("""
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
    """)

    # C. RESOURCE QUANTITY LEDGER - resource_ledger
    op.execute("""
        CREATE TABLE resource_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_id UUID NOT NULL REFERENCES resources(resource_id) ON DELETE RESTRICT,
            delta_qty NUMERIC(10,2) NOT NULL,
            reason VARCHAR(50) NOT NULL,
            ref_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_resource_ledger_res ON resource_ledger(resource_id);
    """)

    # D. LEASED RESERVATIONS - reservation
    op.execute("""
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
    """)
    op.execute("""
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
    """)

    # E. RESOURCE POOLS
    op.execute("""
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
    """)

    # F. EVENT OUTBOX
    op.execute("""
        CREATE TABLE event_outbox (
            event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type VARCHAR(100) NOT NULL,
            pool_id UUID REFERENCES pool(pool_id) ON DELETE SET NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ
        );
        CREATE INDEX idx_event_outbox_unprocessed ON event_outbox(created_at) WHERE processed_at IS NULL;
    """)

    # G. MATCHING DECISION RECORD
    op.execute("""
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
    """)

    # H. REFERENCE DATA & JSONB
    op.execute("ALTER TABLE resources ADD COLUMN capabilities JSONB;")

    # I. IDEMPOTENCY / METADATA
    op.execute("ALTER TABLE emergency_requests ADD COLUMN idempotency_key VARCHAR(100) UNIQUE;")
    op.execute("ALTER TABLE emergency_requests ADD COLUMN source_channel VARCHAR(50);")

    # UPDATE LIFECYCLE
    # Recreate check constraints for allocations and emergency_requests
    op.execute("ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_allocation_status_check;")
    op.execute("""
        ALTER TABLE allocations ADD CONSTRAINT allocations_allocation_status_check 
        CHECK (allocation_status IN ('pending', 'matched', 'proposed', 'reserved', 'dispatched', 'in_transit', 'delivered', 'confirmed', 'fulfilled', 'rejected', 'expired', 'cancelled', 'reassigned'));
    """)

    op.execute("ALTER TABLE emergency_requests DROP CONSTRAINT IF EXISTS emergency_requests_status_check;")
    op.execute("""
        ALTER TABLE emergency_requests ADD CONSTRAINT emergency_requests_status_check 
        CHECK (status IN ('open', 'pending', 'partially_fulfilled', 'fulfilled', 'cancelled', 'expired'));
    """)
    
    # Also update allocation_history entity check constraint
    op.execute("ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_action_check;")
    op.execute("""
        ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_action_check
        CHECK (action IN ('created','status_changed','quantity_updated','matched','dispatched','confirmed','rejected','cancelled','reassigned','escalated','expired','proposed','reserved','fulfilled'));
    """)

    # Replace trigger function for state machine
    op.execute("""
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
    """)


def downgrade() -> None:
    # 1. LIFECYCLE REVERT
    op.execute("""
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
    """)
    op.execute("ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_allocation_status_check;")
    op.execute("""
        ALTER TABLE allocations ADD CONSTRAINT allocations_allocation_status_check 
        CHECK (allocation_status IN ('matched','dispatched','in_transit','delivered','confirmed','rejected','cancelled'));
    """)
    op.execute("ALTER TABLE emergency_requests DROP CONSTRAINT IF EXISTS emergency_requests_status_check;")
    op.execute("""
        ALTER TABLE emergency_requests ADD CONSTRAINT emergency_requests_status_check 
        CHECK (status IN ('open','partially_fulfilled','fulfilled','cancelled','expired'));
    """)
    
    op.execute("ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_action_check;")
    op.execute("""
        ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_action_check
        CHECK (action IN ('created','status_changed','quantity_updated','matched','dispatched','confirmed','rejected','cancelled','reassigned','escalated'));
    """)

    # 2. DROP COLUMNS
    op.execute("ALTER TABLE emergency_requests DROP COLUMN IF EXISTS source_channel;")
    op.execute("ALTER TABLE emergency_requests DROP COLUMN IF EXISTS idempotency_key;")
    op.execute("ALTER TABLE resources DROP COLUMN IF EXISTS capabilities;")

    # 3. DROP TABLES
    op.execute("DROP TABLE IF EXISTS matching_decision;")
    op.execute("DROP TABLE IF EXISTS event_outbox;")
    op.execute("DROP TABLE IF EXISTS request_pool_dependency;")
    op.execute("DROP TABLE IF EXISTS pool;")
    
    op.execute("DROP TRIGGER IF EXISTS trg_reservations_status_change ON reservation;")
    op.execute("DROP TRIGGER IF EXISTS trg_reservations_reserve_qty ON reservation;")
    op.execute("DROP TRIGGER IF EXISTS trg_reservation_updated_at ON reservation;")
    op.execute("DROP FUNCTION IF EXISTS fn_reservations_status_change();")
    op.execute("DROP FUNCTION IF EXISTS fn_reserve_reservation_quantity();")
    op.execute("DROP TABLE IF EXISTS reservation;")
    
    op.execute("DROP TABLE IF EXISTS resource_ledger;")
    op.execute("DROP TABLE IF EXISTS resource_location_history;")
    op.execute("DROP TABLE IF EXISTS hazard_area;")
