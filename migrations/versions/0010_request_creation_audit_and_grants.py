"""request creation: audit trigger + requester grants

Supports the "Create Emergency Request" end-to-end flow
(POST /api/v1/requests) without changing any table structure.

1. Audit: every INSERT into emergency_requests is recorded in the existing
   append-only `allocation_history` table (entity_type='request',
   action='created'), inside the same transaction as the insert. This mirrors
   the existing fn_log_allocation_change() trigger, so request creation is
   audited by the database itself rather than relying on the API layer.
   The function is SECURITY DEFINER so that the RLS-restricted
   `api_requester` role can create a request without being granted direct
   INSERT rights on the audit table.

2. Grants: migration 0009 lets `api_requester` INSERT into
   emergency_requests, but request creation must also (in the same
   transaction) register the request in the pool-dependency index
   (`pool`, `request_pool_dependency`) and emit a transactional outbox event
   (`event_outbox`). Without these grants a requester-role request creation
   fails with "permission denied". Only the minimum privileges are granted:
   SELECT+INSERT on pool (to look up / upsert the zone x type x mobility
   pool), INSERT-only on request_pool_dependency and event_outbox.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08 00:00:00
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_requests_log_insert
            AFTER INSERT ON emergency_requests
            FOR EACH ROW EXECUTE FUNCTION fn_log_request_created();
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fn_log_request_created() FROM PUBLIC;")

    op.execute("GRANT SELECT, INSERT ON pool TO api_requester;")
    op.execute("GRANT INSERT ON request_pool_dependency TO api_requester;")
    op.execute("GRANT INSERT ON event_outbox TO api_requester;")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON event_outbox FROM api_requester;")
    op.execute("REVOKE INSERT ON request_pool_dependency FROM api_requester;")
    op.execute("REVOKE SELECT, INSERT ON pool FROM api_requester;")
    op.execute("DROP TRIGGER IF EXISTS trg_requests_log_insert ON emergency_requests;")
    op.execute("DROP FUNCTION IF EXISTS fn_log_request_created();")
