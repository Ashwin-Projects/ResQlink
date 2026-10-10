"""Database sessions with a PostgreSQL role applied to EVERY transaction.

The backend logs in as `resqlink_app` (NOINHERIT, no table privileges of its
own). Each session carries the application role it acts as in
`session.info["db_role"]`; an `after_begin` hook runs

    SET LOCAL ROLE <db_role>;  SELECT set_config('<claim>', '<value>', true)

at the start of every transaction, including the new transaction that
SQLAlchemy opens after a mid-request `commit()` (the matching engine commits
several times per request; a one-off SET LOCAL at the start of a request would
silently lapse after the first commit). A session without a valid role raises
instead of running unscoped (fail closed), so GRANTs and RLS policies are
always the effective permission check.
"""
from typing import AsyncGenerator, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Only these roles can ever be applied (identifiers cannot be bound parameters).
DB_ROLES = frozenset({"api_coordinator", "api_owner", "api_requester", "api_service", "api_auth"})
CLAIM_SETTINGS = frozenset({"jwt.claims.owner_id", "jwt.claims.requester_id", "jwt.claims.user_id"})


class UnscopedSessionError(RuntimeError):
    """A database transaction was started without an application role."""


class RoleScopedSession(Session):
    """Sync session class behind every AsyncSession created here."""


@event.listens_for(RoleScopedSession, "after_begin")
def _apply_db_role(session, transaction, connection) -> None:
    role = session.info.get("db_role")
    if role not in DB_ROLES:
        raise UnscopedSessionError("database transaction started without an application role; refusing to run unscoped")
    connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
    for setting, value in (session.info.get("db_claims") or {}).items():
        if setting not in CLAIM_SETTINGS:
            raise UnscopedSessionError(f"unexpected claim setting {setting!r}")
        connection.execute(text("SELECT set_config(:setting, :value, true)"), {"setting": setting, "value": str(value)})


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Base factory. Sessions made from it WITHOUT info={"db_role": ...} fail closed
# on their first statement; use role_session / service_session / auth_session.
async_session = sessionmaker(engine, class_=AsyncSession, sync_session_class=RoleScopedSession, expire_on_commit=False)


def role_session(db_role: str, claims: Optional[dict] = None) -> AsyncSession:
    if db_role not in DB_ROLES:
        raise UnscopedSessionError(f"unknown database role {db_role!r}")
    return async_session(info={"db_role": db_role, "db_claims": dict(claims or {})})


def service_session() -> AsyncSession:
    """api_service: outbox processing, incremental re-matching, lease expiry and
    child-row reads for an entity the caller's own role has already been
    allowed to read. No contact columns, no DELETE, no audit writes."""
    return role_session("api_service")


def auth_session() -> AsyncSession:
    """api_auth: may only EXECUTE fn_auth_credentials / fn_auth_record_login /
    fn_auth_session (SECURITY DEFINER); it cannot read any table."""
    return role_session("api_auth")


def claims_for(role: str, subject: str) -> dict:
    if role == "owner":
        return {"jwt.claims.owner_id": subject}
    if role == "requester":
        return {"jwt.claims.requester_id": subject}
    return {"jwt.claims.user_id": subject}


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Deprecated unscoped dependency kept only so old imports fail closed:
    any statement on this session raises UnscopedSessionError."""
    async with async_session() as session:
        yield session


async def database_login_is_privileged() -> Optional[bool]:
    """True when the configured DATABASE_URL logs in as a superuser or a
    BYPASSRLS role (RLS would then still apply after SET ROLE, but a missed
    SET ROLE would not be caught). None if the database is unreachable."""
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = session_user"))).first()
            return bool(row[0]) if row else None
    except Exception:
        return None
