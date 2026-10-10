"""public self-registration for requesters and resource owners

app_users / requesters / owners are not writable by any API role (migration
0015). Registration therefore goes through one SECURITY DEFINER function,
executable only by api_auth, that decides everything a client must not:

* role         only 'requester' or 'owner'; any other role (coordinator) is
               refused here, so coordinator accounts can never be self-created
               even if an API-level check were bypassed
* requester    requesters row (requester_type 'individual', verified_flag false)
               + ACTIVE app_users account
* owner        owners row (verification_status 'pending')
               + INACTIVE app_users account: a coordinator must verify the
               owner and activate the account before it can sign in, so
               unverified organisations cannot publish matchable inventory
* password     only a PBKDF2 hash is stored (app_users CHECK constraint);
               hashing happens in the API, the plain password never reaches SQL
* username     unique case-insensitively (uq_app_users_username)

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

REGISTER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION fn_auth_register(
    p_role TEXT, p_username TEXT, p_password_hash TEXT, p_display_name TEXT,
    p_contact_phone TEXT, p_contact_email TEXT, p_owner_type TEXT)
RETURNS TABLE (user_id UUID, subject_id UUID, role VARCHAR, is_active BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_subject UUID;
    v_user    UUID;
    v_active  BOOLEAN;
BEGIN
    IF p_role IS NULL OR p_role NOT IN ('requester', 'owner') THEN
        RAISE EXCEPTION 'self-registration is not available for role %', COALESCE(p_role, 'none')
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    IF p_role = 'requester' THEN
        INSERT INTO requesters (name, requester_type, contact_phone, contact_email, verified_flag)
        VALUES (p_display_name, 'individual', p_contact_phone, NULLIF(p_contact_email, ''), false)
        RETURNING requesters.requester_id INTO v_subject;
        v_active := true;
        INSERT INTO app_users (username, password_hash, role, requester_id, display_name, is_active)
        VALUES (lower(p_username), p_password_hash, 'requester', v_subject, p_display_name, v_active)
        RETURNING app_users.user_id INTO v_user;
    ELSE
        INSERT INTO owners (name, owner_type, contact_phone, contact_email, verification_status)
        VALUES (p_display_name, p_owner_type, p_contact_phone, NULLIF(p_contact_email, ''), 'pending')
        RETURNING owners.owner_id INTO v_subject;
        v_active := false;
        INSERT INTO app_users (username, password_hash, role, owner_id, display_name, is_active)
        VALUES (lower(p_username), p_password_hash, 'owner', v_subject, p_display_name, v_active)
        RETURNING app_users.user_id INTO v_user;
    END IF;

    RETURN QUERY SELECT v_user, v_subject, p_role::VARCHAR, v_active;
END;
$$;
REVOKE ALL ON FUNCTION fn_auth_register(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_auth_register(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT) TO api_auth;
"""


def upgrade() -> None:
    op.execute(REGISTER_FUNCTION_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fn_auth_register(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT);")
