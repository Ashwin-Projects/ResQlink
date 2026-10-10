"""request status tracking: lifecycle guard + status-change audit

Request Status Tracking reads the request lifecycle straight from the
database, so the database must (a) refuse transitions the lifecycle does not
allow and (b) record WHEN each transition happened. No new statuses and no
table changes are introduced.

1. fn_requests_guard_status_transition (BEFORE UPDATE OF status)
   Encodes the transitions the existing code paths already perform:
     open    <-> pending                (re-queue: LeaseExpirer / LifecycleService)
     open|pending        -> partially_fulfilled | fulfilled
                                         (allocation roll-up, fn_allocations_on_status_change)
     partially_fulfilled -> fulfilled   (allocation roll-up)
     open|pending|partially_fulfilled -> cancelled | expired
   fulfilled, cancelled and expired are terminal. Anything else raises.

2. fn_log_request_status_change (AFTER UPDATE OF status, SECURITY DEFINER)
   Appends a 'request' / 'status_changed' row (old -> new status, quantities)
   to the existing append-only allocation_history table, giving the tracking
   timeline a database timestamp for every request status change.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-08 06:00:00
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_requests_guard_status
            BEFORE UPDATE OF status ON emergency_requests
            FOR EACH ROW EXECUTE FUNCTION fn_requests_guard_status_transition();
        """
    )
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_requests_log_status_change
            AFTER UPDATE OF status ON emergency_requests
            FOR EACH ROW EXECUTE FUNCTION fn_log_request_status_change();
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fn_log_request_status_change() FROM PUBLIC;")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_requests_log_status_change ON emergency_requests;")
    op.execute("DROP FUNCTION IF EXISTS fn_log_request_status_change();")
    op.execute("DROP TRIGGER IF EXISTS trg_requests_guard_status ON emergency_requests;")
    op.execute("DROP FUNCTION IF EXISTS fn_requests_guard_status_transition();")
