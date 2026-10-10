"""resource change -> incremental re-matching: lease revocation functions + persisted outcome

1. fn_lock_resource_leases(resource_id) / fn_revoke_resource_leases(resource_id, ids[])
   (SECURITY DEFINER). When a resource leaves service or its stock is cut, leases
   on it that can no longer be honoured are revoked in the SAME transaction as
   the resource update. api_owner has no privileges on `reservation`, so these
   functions perform the lock / revoke and re-check the caller's authority:
   api_coordinator -> any resource; api_owner -> only resources whose owner_id
   equals jwt.claims.owner_id. Leases are locked FOR UPDATE NOWAIT (a concurrent
   allocate / release of the same lease makes the update fail fast with 55P03
   instead of deadlocking). Revocation = status 'cancelled', so the existing
   trigger returns the quantity and the reservation audit trigger records it.

2. event_outbox.processing_result:

When an outbox event (e.g. 'resource_updated') is processed, the processor
stores what actually happened (affected pools, affected request IDs, leases
created / revoked, measured duration) next to processed_at, so the result of
every incremental re-match run is auditable from the database and can be shown
in the UI without recomputing or inventing anything.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08 22:00:00
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )
    op.execute(
        """
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
        """
    )
    op.execute(
        """
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
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fn_assert_resource_manager(UUID) FROM PUBLIC;")
    op.execute("REVOKE ALL ON FUNCTION fn_lock_resource_leases(UUID) FROM PUBLIC;")
    op.execute("REVOKE ALL ON FUNCTION fn_revoke_resource_leases(UUID, UUID[]) FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION fn_lock_resource_leases(UUID) TO api_coordinator, api_owner;")
    op.execute("GRANT EXECUTE ON FUNCTION fn_revoke_resource_leases(UUID, UUID[]) TO api_coordinator, api_owner;")

    op.execute("ALTER TABLE event_outbox ADD COLUMN processing_result JSONB;")
    op.execute(
        """
        CREATE INDEX idx_event_outbox_processed_results
            ON event_outbox (processed_at DESC) WHERE processing_result IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_event_outbox_processed_results;")
    op.execute("ALTER TABLE event_outbox DROP COLUMN IF EXISTS processing_result;")
    op.execute("DROP FUNCTION IF EXISTS fn_revoke_resource_leases(UUID, UUID[]);")
    op.execute("DROP FUNCTION IF EXISTS fn_lock_resource_leases(UUID);")
    op.execute("DROP FUNCTION IF EXISTS fn_assert_resource_manager(UUID);")
