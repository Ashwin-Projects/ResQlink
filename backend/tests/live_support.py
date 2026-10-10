"""Shared helpers for the live-database API tests.

* The API under test logs in as resqlink_app (DATABASE_URL) and authenticates
  callers with real JWTs: tests obtain them through POST /api/v1/auth/login
  with the seeded demo accounts (scripts/seed_data.sql), never by minting
  tokens themselves.
* Test setup / verification SQL (direct INSERTs, reading audit tables) needs
  more than any application role has, so it runs on a separate admin engine:
  ADMIN_DATABASE_URL (default: the docker-compose superuser `resqlink`).

    cd backend
    DATABASE_URL=postgresql+asyncpg://resqlink_app:<APP_DB_PASSWORD>@localhost:5432/resqlink \
    ADMIN_DATABASE_URL=postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink \
        python -m pytest -o asyncio_mode=auto tests/ -v
"""
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ADMIN_DATABASE_URL = os.environ.get(
    "ADMIN_DATABASE_URL", "postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink")
DEMO_PASSWORD = os.environ.get("RESQLINK_DEMO_PASSWORD", "ResQLink-Demo-2026!")

# NullPool: asyncpg connections are bound to the per-test event loop.
admin_engine = create_async_engine(ADMIN_DATABASE_URL, poolclass=NullPool)

COORDINATOR = "asha.verma"
OWNER_A, OWNER_B = "sdra.owner", "coastal.owner"
REQUESTER_A, REQUESTER_B = "ramesh.kumar", "lakshmi.iyer"
# seeded subject id -> demo account
USERNAME_BY_SUBJECT = {
    "b1111111-1111-1111-1111-111111111111": COORDINATOR,
    "a1111111-1111-1111-1111-111111111111": OWNER_A,
    "a2222222-2222-2222-2222-222222222222": OWNER_B,
    "f1111111-1111-1111-1111-111111111111": REQUESTER_A,
    "f2222222-2222-2222-2222-222222222222": REQUESTER_B,
}


async def login_headers(client, username: str) -> dict:
    res = await client.post("/api/v1/auth/login", json={"username": username, "password": DEMO_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def headers_for_subject(client, subject_id) -> dict:
    return await login_headers(client, USERNAME_BY_SUBJECT[str(subject_id)])


def other_subject(subject_id, role: str) -> str:
    """A different seeded subject of the same role (cross-owner / cross-requester checks)."""
    pairs = {"owner": ("a1111111-1111-1111-1111-111111111111", "a2222222-2222-2222-2222-222222222222"),
             "requester": ("f1111111-1111-1111-1111-111111111111", "f2222222-2222-2222-2222-222222222222")}[role]
    return pairs[1] if str(subject_id) == pairs[0] else pairs[0]


async def live_db_available(*probe_sql: str):
    """Returns None if the admin connection works and every probe succeeds, else the error."""
    try:
        async with admin_engine.connect() as conn:
            for sql in probe_sql or ("SELECT 1 FROM app_users LIMIT 1",):
                await conn.execute(text(sql))
        return None
    except Exception as e:  # pragma: no cover - environment dependent
        return e
