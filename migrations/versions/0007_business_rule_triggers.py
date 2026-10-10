"""add trigger functions: quantity reservation/release, allocation state
machine, cascade-cancel, derived status sync, append-only audit log,
auto-logging of allocation changes

Revision ID: 0007
Revises: 0006
Create Date: 2026-01-01 00:06:00
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("CREATE TRIGGER trg_owners_updated_at    BEFORE UPDATE ON owners    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();")
    op.execute("CREATE TRIGGER trg_shelters_updated_at  BEFORE UPDATE ON shelters  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();")
    op.execute("CREATE TRIGGER trg_resources_updated_at BEFORE UPDATE ON resources FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();")
    op.execute("CREATE TRIGGER trg_requests_updated_at  BEFORE UPDATE ON emergency_requests FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();")

    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_allocations_reserve_qty
            BEFORE INSERT ON allocations
            FOR EACH ROW EXECUTE FUNCTION fn_reserve_resource_quantity();
        """
    )

    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_allocations_status_change
            BEFORE UPDATE ON allocations
            FOR EACH ROW EXECUTE FUNCTION fn_allocations_on_status_change();
        """
    )

    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_requests_cascade_cancel
            AFTER UPDATE OF status ON emergency_requests
            FOR EACH ROW EXECUTE FUNCTION fn_requests_cascade_cancel();
        """
    )

    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_resources_sync_status
            BEFORE INSERT OR UPDATE OF quantity_available ON resources
            FOR EACH ROW EXECUTE FUNCTION fn_resources_sync_status();
        """
    )

    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_shelters_sync_status
            BEFORE INSERT OR UPDATE OF capacity_occupied ON shelters
            FOR EACH ROW EXECUTE FUNCTION fn_shelters_sync_status();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_prevent_history_mutation() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'allocation_history is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_history_no_update
            BEFORE UPDATE OR DELETE ON allocation_history
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_history_mutation();
        """
    )

    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_allocations_log_insert
            AFTER INSERT ON allocations
            FOR EACH ROW EXECUTE FUNCTION fn_log_allocation_change();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_allocations_log_update
            AFTER UPDATE ON allocations
            FOR EACH ROW EXECUTE FUNCTION fn_log_allocation_change();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_allocations_log_update ON allocations;")
    op.execute("DROP TRIGGER IF EXISTS trg_allocations_log_insert ON allocations;")
    op.execute("DROP FUNCTION IF EXISTS fn_log_allocation_change();")

    op.execute("DROP TRIGGER IF EXISTS trg_history_no_update ON allocation_history;")
    op.execute("DROP FUNCTION IF EXISTS fn_prevent_history_mutation();")

    op.execute("DROP TRIGGER IF EXISTS trg_shelters_sync_status ON shelters;")
    op.execute("DROP FUNCTION IF EXISTS fn_shelters_sync_status();")

    op.execute("DROP TRIGGER IF EXISTS trg_resources_sync_status ON resources;")
    op.execute("DROP FUNCTION IF EXISTS fn_resources_sync_status();")

    op.execute("DROP TRIGGER IF EXISTS trg_requests_cascade_cancel ON emergency_requests;")
    op.execute("DROP FUNCTION IF EXISTS fn_requests_cascade_cancel();")

    op.execute("DROP TRIGGER IF EXISTS trg_allocations_status_change ON allocations;")
    op.execute("DROP FUNCTION IF EXISTS fn_allocations_on_status_change();")

    op.execute("DROP TRIGGER IF EXISTS trg_allocations_reserve_qty ON allocations;")
    op.execute("DROP FUNCTION IF EXISTS fn_reserve_resource_quantity();")

    op.execute("DROP TRIGGER IF EXISTS trg_requests_updated_at ON emergency_requests;")
    op.execute("DROP TRIGGER IF EXISTS trg_resources_updated_at ON resources;")
    op.execute("DROP TRIGGER IF EXISTS trg_shelters_updated_at ON shelters;")
    op.execute("DROP TRIGGER IF EXISTS trg_owners_updated_at ON owners;")
    op.execute("DROP FUNCTION IF EXISTS fn_set_updated_at();")
