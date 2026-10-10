"""create owners, system_users, zones (reference / master data)

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-01 00:01:00
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE owners (
            owner_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                 VARCHAR(150) NOT NULL,
            owner_type           VARCHAR(20)  NOT NULL
                                  CHECK (owner_type IN ('government','ngo','private','community')),
            contact_phone        VARCHAR(20)  NOT NULL,
            contact_email        VARCHAR(150),
            verification_status  VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                  CHECK (verification_status IN ('verified','pending','suspended')),
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE system_users (
            user_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                 VARCHAR(150) NOT NULL,
            role                 VARCHAR(20)  NOT NULL
                                  CHECK (role IN ('coordinator','dispatcher','admin','field_verifier','auditor')),
            agency_affiliation   VARCHAR(150),
            contact_info         VARCHAR(150),
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE zones (
            zone_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            zone_name            VARCHAR(150) NOT NULL,
            zone_type            VARCHAR(20)  NOT NULL
                                  CHECK (zone_type IN ('district','ward','village','shelter_site')),
            parent_zone_id       UUID REFERENCES zones(zone_id) ON DELETE SET NULL,
            location             geography(Point,4326) NOT NULL,
            risk_level           VARCHAR(10)  NOT NULL DEFAULT 'medium'
                                  CHECK (risk_level IN ('critical','high','medium','low')),
            population_estimate  INTEGER CHECK (population_estimate IS NULL OR population_estimate >= 0),
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT zones_parent_not_self CHECK (parent_zone_id IS NULL OR parent_zone_id <> zone_id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS zones;")
    op.execute("DROP TABLE IF EXISTS system_users;")
    op.execute("DROP TABLE IF EXISTS owners;")
