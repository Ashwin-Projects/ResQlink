"""enable postgis and pgcrypto extensions

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")


def downgrade() -> None:
    # Extensions are left in place on downgrade by default, since other
    # databases/schemas on the same cluster may depend on them. Uncomment
    # if you are certain this is the only consumer.
    # op.execute("DROP EXTENSION IF EXISTS postgis;")
    # op.execute("DROP EXTENSION IF EXISTS pgcrypto;")
    pass
