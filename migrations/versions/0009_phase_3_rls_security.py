"""phase 3 rls security

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create application roles
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_coordinator') THEN CREATE ROLE api_coordinator; END IF; END $$;")
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_owner') THEN CREATE ROLE api_owner; END IF; END $$;")
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_requester') THEN CREATE ROLE api_requester; END IF; END $$;")
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_anon') THEN CREATE ROLE api_anon; END IF; END $$;")

    # Grant basic usage
    op.execute("GRANT USAGE ON SCHEMA public TO api_coordinator, api_owner, api_requester, api_anon;")

    # Grant table permissions
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO api_coordinator;")
    op.execute("GRANT SELECT ON zones, shelters, hazard_area TO api_owner, api_requester, api_anon;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON resources, owners TO api_owner;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON emergency_requests, requesters TO api_requester;")
    
    # Ensure sequences can be used (if any, although we use UUIDs mostly)
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO api_coordinator, api_owner, api_requester;")

    # Enable RLS
    op.execute("ALTER TABLE resources ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE emergency_requests ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE requesters ENABLE ROW LEVEL SECURITY;")

    # Create policies for resources (owners can see/edit their own, coordinators can see/edit all, requesters can see available)
    # Using current_setting('jwt.claims.owner_id', true) to match the logged-in owner
    op.execute("""
        CREATE POLICY owner_resource_policy ON resources
        FOR ALL TO api_owner
        USING (owner_id::text = current_setting('jwt.claims.owner_id', true));
    """)
    op.execute("""
        CREATE POLICY coordinator_resource_policy ON resources
        FOR ALL TO api_coordinator
        USING (true);
    """)
    op.execute("""
        CREATE POLICY requester_resource_policy ON resources
        FOR SELECT TO api_requester
        USING (status = 'available');
    """)

    # Create policies for requesters (they can see/edit their own data, coordinators can see all)
    op.execute("""
        CREATE POLICY requester_self_policy ON requesters
        FOR ALL TO api_requester
        USING (requester_id::text = current_setting('jwt.claims.requester_id', true));
    """)
    op.execute("""
        CREATE POLICY coordinator_requesters_policy ON requesters
        FOR ALL TO api_coordinator
        USING (true);
    """)

    # Create policies for emergency_requests
    op.execute("""
        CREATE POLICY requester_requests_policy ON emergency_requests
        FOR ALL TO api_requester
        USING (requester_id::text = current_setting('jwt.claims.requester_id', true));
    """)
    op.execute("""
        CREATE POLICY coordinator_requests_policy ON emergency_requests
        FOR ALL TO api_coordinator
        USING (true);
    """)

def downgrade() -> None:
    # Drop policies
    op.execute("DROP POLICY IF EXISTS owner_resource_policy ON resources;")
    op.execute("DROP POLICY IF EXISTS coordinator_resource_policy ON resources;")
    op.execute("DROP POLICY IF EXISTS requester_resource_policy ON resources;")
    
    op.execute("DROP POLICY IF EXISTS requester_self_policy ON requesters;")
    op.execute("DROP POLICY IF EXISTS coordinator_requesters_policy ON requesters;")
    
    op.execute("DROP POLICY IF EXISTS requester_requests_policy ON emergency_requests;")
    op.execute("DROP POLICY IF EXISTS coordinator_requests_policy ON emergency_requests;")
    
    # Disable RLS
    op.execute("ALTER TABLE resources DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE emergency_requests DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE requesters DISABLE ROW LEVEL SECURITY;")
    
    # Revoke permissions (assuming a full rollback deletes roles)
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM api_coordinator, api_owner, api_requester, api_anon;")
    op.execute("REVOKE USAGE ON SCHEMA public FROM api_coordinator, api_owner, api_requester, api_anon;")
    
    # Drop roles
    op.execute("DROP ROLE IF EXISTS api_coordinator;")
    op.execute("DROP ROLE IF EXISTS api_owner;")
    op.execute("DROP ROLE IF EXISTS api_requester;")
    op.execute("DROP ROLE IF EXISTS api_anon;")
