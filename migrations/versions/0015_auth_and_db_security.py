"""authentication accounts + database-level security hardening

Before this migration the API could run every statement as the database
owner (superuser), so the RLS policies of 0009 were never actually applied,
and the api_* roles were broader than the application needs. This migration
makes PostgreSQL itself enforce who may do what:

1. Login role and per-purpose roles
   * resqlink_app  - the ONLY role the backend logs in as (password is set at
                     deploy time, never in a migration). NOSUPERUSER,
                     NOBYPASSRLS, NOINHERIT: connected but without SET ROLE
                     it can read nothing. Every transaction must
                     `SET LOCAL ROLE` to one of the roles below.
   * api_coordinator / api_owner / api_requester - one per authenticated
                     application role (JWT role claim).
   * api_service   - background / follow-up work (outbox processing,
                     incremental re-matching, lease expiry, tracking child
                     reads after an RLS-checked parent read). No access to
                     contact columns, no DELETE, no audit writes.
   * api_auth      - the login endpoint: may only EXECUTE the three
                     SECURITY DEFINER auth functions; cannot read any table.
   * api_anon      - stripped of every table privilege (unused; kept so old
                     grants cannot silently reappear).

2. app_users - application accounts (PBKDF2-SHA256 hashes, lockout fields),
   each linked to exactly one subject (requester / owner / system user).
   RLS enabled with NO policies and no table grants to any api role:
   only the SECURITY DEFINER functions fn_auth_credentials,
   fn_auth_record_login and fn_auth_session can touch it.

3. Least privilege (REVOKE then GRANT)
   * coordinator: SELECT everywhere except app_users; INSERT/UPDATE only on
     resources, emergency_requests, reservation, allocations; INSERT only on
     pool, request_pool_dependency, event_outbox, matching_decision.
     No DELETE / TRUNCATE anywhere.
   * requester: may no longer UPDATE emergency_requests (status /
     quantity_fulfilled were writable) nor INSERT/UPDATE requesters
     (verified_flag was writable); may update only its own contact columns;
     reads only the public columns of available resources.
   * owner: may no longer INSERT/UPDATE owners (any owners row was writable);
     owners gets RLS (owner sees only itself).
   * audit / ledger tables (allocation_history, resource_ledger,
     resource_location_history) are written only by SECURITY DEFINER
     triggers; append-only triggers now also block UPDATE / DELETE /
     TRUNCATE on the two ledgers (allocation_history already had one).

4. fn_assert_resource_manager no longer treats "no role" as trusted.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-09 10:00:00
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

API_ROLES = "api_coordinator, api_owner, api_requester, api_service, api_auth, api_anon"


def upgrade() -> None:
    # ------------------------------------------------------------------ roles
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_service') THEN
                CREATE ROLE api_service NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'api_auth') THEN
                CREATE ROLE api_auth NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'resqlink_app') THEN
                CREATE ROLE resqlink_app NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute("ALTER ROLE resqlink_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS NOREPLICATION;")
    op.execute(
        """
        ALTER ROLE api_coordinator NOLOGIN NOBYPASSRLS;
        ALTER ROLE api_owner       NOLOGIN NOBYPASSRLS;
        ALTER ROLE api_requester   NOLOGIN NOBYPASSRLS;
        ALTER ROLE api_service     NOLOGIN NOBYPASSRLS;
        ALTER ROLE api_auth        NOLOGIN NOBYPASSRLS;
        ALTER ROLE api_anon        NOLOGIN NOBYPASSRLS;
        """
    )
    op.execute("GRANT api_coordinator, api_owner, api_requester, api_service, api_auth TO resqlink_app;")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC;")
    op.execute("GRANT USAGE ON SCHEMA public TO api_coordinator, api_owner, api_requester, api_service, api_auth;")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM api_anon;")
    op.execute("REVOKE USAGE ON SCHEMA public FROM api_anon;")

    # -------------------------------------------------------------- app_users
    op.execute(
        """
        CREATE TABLE app_users (
            user_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username         VARCHAR(64)  NOT NULL CHECK (username ~ '^[a-z0-9._-]{3,64}$'),
            password_hash    TEXT         NOT NULL CHECK (password_hash LIKE 'pbkdf2_sha256$%'),
            role             VARCHAR(20)  NOT NULL CHECK (role IN ('requester', 'owner', 'coordinator')),
            requester_id     UUID REFERENCES requesters(requester_id),
            owner_id         UUID REFERENCES owners(owner_id),
            system_user_id   UUID REFERENCES system_users(user_id),
            display_name     VARCHAR(150) NOT NULL,
            is_active        BOOLEAN      NOT NULL DEFAULT true,
            failed_attempts  INTEGER      NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
            locked_until     TIMESTAMPTZ,
            last_login_at    TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT app_users_role_subject CHECK (
                (role = 'requester'   AND requester_id   IS NOT NULL AND owner_id IS NULL AND system_user_id IS NULL) OR
                (role = 'owner'       AND owner_id       IS NOT NULL AND requester_id IS NULL AND system_user_id IS NULL) OR
                (role = 'coordinator' AND system_user_id IS NOT NULL AND requester_id IS NULL AND owner_id IS NULL)
            )
        );
        CREATE UNIQUE INDEX uq_app_users_username ON app_users (lower(username));
        CREATE TRIGGER trg_app_users_updated_at BEFORE UPDATE ON app_users
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
        ALTER TABLE app_users ENABLE ROW LEVEL SECURITY;
        """
    )
    op.execute(f"REVOKE ALL ON app_users FROM PUBLIC, {API_ROLES}, resqlink_app;")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_auth_credentials(p_username TEXT)
        RETURNS TABLE (user_id UUID, password_hash TEXT, role VARCHAR, subject_id UUID,
                       display_name VARCHAR, is_active BOOLEAN, locked_until TIMESTAMPTZ)
        LANGUAGE sql STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT u.user_id, u.password_hash, u.role,
                   COALESCE(u.requester_id, u.owner_id, u.system_user_id),
                   u.display_name, u.is_active, u.locked_until
            FROM app_users u
            WHERE lower(u.username) = lower(p_username);
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_auth_record_login(p_user_id UUID, p_success BOOLEAN)
        RETURNS VOID
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_failed INTEGER;
            v_locked TIMESTAMPTZ;
        BEGIN
            SELECT u.failed_attempts, u.locked_until INTO v_failed, v_locked
            FROM app_users u WHERE u.user_id = p_user_id FOR UPDATE;
            IF NOT FOUND THEN
                RETURN;
            END IF;
            IF p_success THEN
                UPDATE app_users SET failed_attempts = 0, locked_until = NULL, last_login_at = now()
                WHERE app_users.user_id = p_user_id;
                RETURN;
            END IF;
            -- An expired lock starts a fresh window of attempts.
            IF v_locked IS NOT NULL AND v_locked <= now() THEN
                v_failed := 0;
                v_locked := NULL;
            END IF;
            v_failed := v_failed + 1;
            IF v_failed >= 5 THEN
                v_locked := now() + interval '15 minutes';
            END IF;
            UPDATE app_users SET failed_attempts = v_failed, locked_until = v_locked
            WHERE app_users.user_id = p_user_id;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_auth_session(p_user_id UUID, p_role TEXT, p_subject_id UUID)
        RETURNS BOOLEAN
        LANGUAGE sql STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM app_users u
                WHERE u.user_id = p_user_id
                  AND u.is_active
                  AND u.role = p_role
                  AND COALESCE(u.requester_id, u.owner_id, u.system_user_id) = p_subject_id
            );
        $$;
        """
    )
    for fn in ("fn_auth_credentials(TEXT)", "fn_auth_record_login(UUID, BOOLEAN)", "fn_auth_session(UUID, TEXT, UUID)"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO api_auth;")

    # ------------------------------------------- audit / ledger: append-only
    # allocation inserts / status changes are logged by this trigger; with no
    # INSERT grant on allocation_history left for any api role it has to run
    # with the table owner's rights (same body as 0007).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_log_allocation_change() RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by)
                VALUES ('allocation', NEW.allocation_id, NEW.allocation_id, 'created', NULL, to_jsonb(NEW), NEW.matched_by);
            ELSIF TG_OP = 'UPDATE' AND NEW.allocation_status <> OLD.allocation_status THEN
                INSERT INTO allocation_history (entity_type, entity_id, allocation_id, action, old_value, new_value, performed_by)
                VALUES ('allocation', NEW.allocation_id, NEW.allocation_id, 'status_changed', to_jsonb(OLD), to_jsonb(NEW), NEW.matched_by);
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fn_log_allocation_change() FROM PUBLIC;")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_prevent_append_only_mutation() RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: % is not permitted', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
        CREATE TRIGGER trg_resource_ledger_append_only BEFORE UPDATE OR DELETE ON resource_ledger
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_append_only_mutation();
        CREATE TRIGGER trg_resource_ledger_no_truncate BEFORE TRUNCATE ON resource_ledger
            FOR EACH STATEMENT EXECUTE FUNCTION fn_prevent_append_only_mutation();
        CREATE TRIGGER trg_location_history_append_only BEFORE UPDATE OR DELETE ON resource_location_history
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_append_only_mutation();
        CREATE TRIGGER trg_location_history_no_truncate BEFORE TRUNCATE ON resource_location_history
            FOR EACH STATEMENT EXECUTE FUNCTION fn_prevent_append_only_mutation();
        CREATE TRIGGER trg_history_no_truncate BEFORE TRUNCATE ON allocation_history
            FOR EACH STATEMENT EXECUTE FUNCTION fn_prevent_append_only_mutation();
        """
    )

    # ------------------------------------------------------------ coordinator
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM api_coordinator;")
    op.execute(
        """
        GRANT SELECT ON zones, owners, system_users, shelters, hazard_area,
                        resources, resource_zone_coverage, resource_ledger, resource_location_history,
                        requesters, emergency_requests, pool, request_pool_dependency,
                        reservation, allocations, allocation_history, matching_decision, event_outbox
            TO api_coordinator;
        GRANT INSERT, UPDATE ON resources, emergency_requests, reservation, allocations TO api_coordinator;
        GRANT INSERT ON pool, request_pool_dependency, event_outbox, matching_decision TO api_coordinator;
        """
    )
    op.execute(
        """
        ALTER TABLE owners ENABLE ROW LEVEL SECURITY;
        CREATE POLICY coordinator_owners_policy ON owners FOR SELECT TO api_coordinator USING (true);
        """
    )

    # -------------------------------------------------------------- requester
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON emergency_requests FROM api_requester;")
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON requesters FROM api_requester;")
    op.execute("GRANT UPDATE (contact_phone, contact_email) ON requesters TO api_requester;")
    op.execute(
        """
        GRANT SELECT (resource_id, current_zone_id, resource_type, resource_subtype, quantity_total,
                      quantity_available, unit_of_measure, status, location)
            ON resources TO api_requester;
        """
    )

    # ------------------------------------------------------------------ owner
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON owners FROM api_owner;")
    op.execute("REVOKE DELETE, TRUNCATE ON resources FROM api_owner;")
    op.execute(
        """
        CREATE POLICY owner_self_policy ON owners FOR SELECT TO api_owner
            USING (owner_id::text = current_setting('jwt.claims.owner_id', true));
        """
    )

    # ---------------------------------------------------------------- service
    op.execute(
        """
        GRANT SELECT ON zones, system_users, shelters, hazard_area,
                        resources, resource_zone_coverage, resource_ledger, resource_location_history,
                        emergency_requests, pool, request_pool_dependency,
                        reservation, allocations, allocation_history, matching_decision, event_outbox
            TO api_service;
        GRANT SELECT (owner_id, name, owner_type, verification_status) ON owners TO api_service;
        GRANT SELECT (requester_id, name, requester_type, verified_flag, created_at) ON requesters TO api_service;
        GRANT INSERT ON reservation, matching_decision, event_outbox TO api_service;
        GRANT UPDATE ON resources, emergency_requests, reservation, allocations, event_outbox TO api_service;
        CREATE POLICY service_resources_policy  ON resources          FOR ALL    TO api_service USING (true);
        CREATE POLICY service_requests_policy   ON emergency_requests FOR ALL    TO api_service USING (true);
        CREATE POLICY service_requesters_policy ON requesters         FOR SELECT TO api_service USING (true);
        CREATE POLICY service_owners_policy     ON owners             FOR SELECT TO api_service USING (true);
        """
    )

    # ---------------------------------------- lease functions: fail closed
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
            ELSIF v_role IS DISTINCT FROM 'api_coordinator' THEN
                RAISE EXCEPTION 'role % may not manage resource leases', COALESCE(v_role, 'none')
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
        END;
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION fn_assert_resource_manager(UUID) FROM PUBLIC;")


def downgrade() -> None:
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
        DROP POLICY IF EXISTS service_resources_policy ON resources;
        DROP POLICY IF EXISTS service_requests_policy ON emergency_requests;
        DROP POLICY IF EXISTS service_requesters_policy ON requesters;
        DROP POLICY IF EXISTS service_owners_policy ON owners;
        DROP POLICY IF EXISTS owner_self_policy ON owners;
        DROP POLICY IF EXISTS coordinator_owners_policy ON owners;
        ALTER TABLE owners DISABLE ROW LEVEL SECURITY;
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM api_service;
        REVOKE SELECT (resource_id, current_zone_id, resource_type, resource_subtype, quantity_total,
                       quantity_available, unit_of_measure, status, location) ON resources FROM api_requester;
        REVOKE UPDATE (contact_phone, contact_email) ON requesters FROM api_requester;
        GRANT SELECT, INSERT, UPDATE ON emergency_requests, requesters TO api_requester;
        GRANT SELECT, INSERT, UPDATE ON resources, owners TO api_owner;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO api_coordinator;
        GRANT USAGE ON SCHEMA public TO api_anon;
        GRANT SELECT ON zones, shelters, hazard_area TO api_anon;
        DROP TRIGGER IF EXISTS trg_resource_ledger_append_only ON resource_ledger;
        DROP TRIGGER IF EXISTS trg_resource_ledger_no_truncate ON resource_ledger;
        DROP TRIGGER IF EXISTS trg_location_history_append_only ON resource_location_history;
        DROP TRIGGER IF EXISTS trg_location_history_no_truncate ON resource_location_history;
        DROP TRIGGER IF EXISTS trg_history_no_truncate ON allocation_history;
        DROP FUNCTION IF EXISTS fn_prevent_append_only_mutation();
        ALTER FUNCTION fn_log_allocation_change() SECURITY INVOKER;
        DROP FUNCTION IF EXISTS fn_auth_session(UUID, TEXT, UUID);
        DROP FUNCTION IF EXISTS fn_auth_record_login(UUID, BOOLEAN);
        DROP FUNCTION IF EXISTS fn_auth_credentials(TEXT);
        DROP TABLE IF EXISTS app_users;
        REVOKE api_coordinator, api_owner, api_requester, api_service, api_auth FROM resqlink_app;
        """
    )
    # Roles are cluster-wide and may be used by other databases; they are left in place.
