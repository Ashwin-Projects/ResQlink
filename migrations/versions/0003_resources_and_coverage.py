"""create shelters, resources, resource_zone_coverage

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-01 00:02:00
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )

    op.execute(
        """
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
        """
    )

    op.execute(
        """
        CREATE TABLE resource_zone_coverage (
            coverage_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            resource_id          UUID NOT NULL REFERENCES resources(resource_id) ON DELETE CASCADE,
            zone_id              UUID NOT NULL REFERENCES zones(zone_id) ON DELETE CASCADE,
            coverage_priority    INTEGER NOT NULL DEFAULT 100 CHECK (coverage_priority >= 0),
            CONSTRAINT uq_resource_zone UNIQUE (resource_id, zone_id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS resource_zone_coverage;")
    op.execute("DROP TABLE IF EXISTS resources;")
    op.execute("DROP TABLE IF EXISTS shelters;")
