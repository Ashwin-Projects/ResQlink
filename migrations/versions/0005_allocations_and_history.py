"""create allocations (M:M junction w/ lifecycle) and allocation_history (audit log)

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-01 00:04:00
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )

    op.execute(
        """
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
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS allocation_history;")
    op.execute("DROP TABLE IF EXISTS allocations;")
