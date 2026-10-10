"""resource management: audit + ledger + location history for operator changes

Supports Add / Update Resource (POST /api/v1/resources, PATCH
/api/v1/resources/{id}) with database-written history. No table structure
changes except one allowed audit action value.

fn_log_resource_change (SECURITY DEFINER) fires on
    AFTER INSERT ON resources
    AFTER UPDATE OF quantity_total, status, current_zone_id, location,
                    capabilities, resource_subtype, condition_notes,
                    last_verified_at ON resources
and writes, in the same transaction:
  * allocation_history  entity_type='resource': 'created' | 'status_changed' |
                        'quantity_updated' | 'updated' with only the changed fields
  * resource_ledger     (append-only) 'initial_stock' on insert,
                        'stock_adjustment' when quantity_total changes
  * resource_location_history  on insert and whenever the location changes

quantity_available is deliberately NOT in the column list: the reservation /
allocation quantity triggers on the matching path update only that column, so
this trigger adds no work to matching. Operator updates through the API always
also set last_verified_at, so they always fire it, and the row diff then
includes any quantity_available change.

api_owner gets INSERT on event_outbox so an owner's resource change can emit
its outbox event in the same transaction (as api_requester got in 0010).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-08 18:00:00
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_action_check;")
    op.execute(
        """
        ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_action_check
            CHECK (action IN ('created','status_changed','quantity_updated','matched','dispatched','confirmed','rejected',
                              'cancelled','reassigned','escalated','expired','proposed','reserved','fulfilled','updated'));
        """
    )
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_resources_log_insert
            AFTER INSERT ON resources
            FOR EACH ROW EXECUTE FUNCTION fn_log_resource_change();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_resources_log_update
            AFTER UPDATE OF quantity_total, status, current_zone_id, location, capabilities,
                            resource_subtype, condition_notes, last_verified_at ON resources
            FOR EACH ROW EXECUTE FUNCTION fn_log_resource_change();
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fn_log_resource_change() FROM PUBLIC;")
    op.execute("GRANT INSERT ON event_outbox TO api_owner;")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON event_outbox FROM api_owner;")
    op.execute("DROP TRIGGER IF EXISTS trg_resources_log_update ON resources;")
    op.execute("DROP TRIGGER IF EXISTS trg_resources_log_insert ON resources;")
    op.execute("DROP FUNCTION IF EXISTS fn_log_resource_change();")
    op.execute("ALTER TABLE allocation_history DROP CONSTRAINT IF EXISTS allocation_history_action_check;")
    op.execute(
        """
        ALTER TABLE allocation_history ADD CONSTRAINT allocation_history_action_check
            CHECK (action IN ('created','status_changed','quantity_updated','matched','dispatched','confirmed','rejected',
                              'cancelled','reassigned','escalated','expired','proposed','reserved','fulfilled')) NOT VALID;
        """
    )
