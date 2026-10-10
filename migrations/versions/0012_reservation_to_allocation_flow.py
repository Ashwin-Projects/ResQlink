"""reservation -> allocation workflow: exactly-once conversion + reservation audit

Supports the end-to-end Request -> Match -> Reserve -> Allocate -> Confirm flow
without changing the existing quantity triggers or state machines.

1. allocations.reservation_id (nullable FK -> reservation) with a UNIQUE
   partial index: a leased reservation can be converted into AT MOST ONE
   allocation, enforced by the database even under concurrent requests.
   Quantity accounting is unchanged: the reservation INSERT already
   decremented resources.quantity_available; the reservation moves to
   'completed' (no release) and the allocation is inserted as 'reserved'
   (fn_reserve_resource_quantity does not decrement 'reserved'), so the
   quantity is carried over exactly once.

2. Reservation audit: allocation_history.entity_type gains 'reservation';
   trg_reservation_audit appends 'created' / 'status_changed' rows for every
   reservation insert and status change (matching engine leases, lease
   expiry, conversion, release), so the whole workflow is audited by the
   database itself.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-08 12:00:00
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE allocations
            ADD COLUMN reservation_id UUID REFERENCES reservation(reservation_id) ON DELETE SET NULL;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_allocations_reservation
            ON allocations (reservation_id) WHERE reservation_id IS NOT NULL;
        """
    )
    op.execute("ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_entity_type_check;")
    op.execute(
        """
        ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_entity_type_check
            CHECK (entity_type IN ('request','resource','allocation','owner','reservation'));
        """
    )
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reservation_audit
            AFTER INSERT OR UPDATE OF status ON reservation
            FOR EACH ROW EXECUTE FUNCTION fn_log_reservation_change();
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fn_log_reservation_change() FROM PUBLIC;")
    op.execute("CREATE INDEX idx_reservation_request_status ON reservation (request_id, status);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_reservation_request_status;")
    op.execute("DROP TRIGGER IF EXISTS trg_reservation_audit ON reservation;")
    op.execute("DROP FUNCTION IF EXISTS fn_log_reservation_change();")
    op.execute("ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_entity_type_check;")
    op.execute(
        """
        ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_entity_type_check
            CHECK (entity_type IN ('request','resource','allocation','owner')) NOT VALID;
        """
    )  # NOT VALID: allocation_history is append-only, existing 'reservation' rows cannot be deleted
    op.execute("DROP INDEX IF EXISTS uq_allocations_reservation;")
    op.execute("ALTER TABLE allocations DROP COLUMN IF EXISTS reservation_id;")
