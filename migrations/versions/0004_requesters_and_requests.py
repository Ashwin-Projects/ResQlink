"""create requesters, emergency_requests

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-01 00:03:00
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )

    op.execute(
        """
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
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS emergency_requests;")
    op.execute("DROP TABLE IF EXISTS requesters;")
