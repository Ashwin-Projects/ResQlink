"""Requester profiles: contact details are private.

Who can see a requester's contact_phone / contact_email:
  * the requester itself (RLS policy requester_self_policy: own row only),
  * a coordinator, on the single-requester detail endpoint.
List responses for coordinators carry masked contact details only. Owners have
no privilege on `requesters` at all (403), and api_service has a column-level
SELECT grant that excludes the contact columns, so background code cannot
leak them either.

A requester may change only its own contact columns: the column-level
UPDATE (contact_phone, contact_email) grant + RLS enforce this in PostgreSQL
(verified_flag / name / requester_type are not updatable by api_requester).
"""
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import exc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.request_intake import _pg_code

DETAIL_SQL = text("""
    SELECT requester_id, name, requester_type, verified_flag, contact_phone, contact_email
    FROM requesters WHERE requester_id = :rid
""")
LIST_SQL = text("""
    SELECT requester_id, name, requester_type, verified_flag, contact_phone, contact_email
    FROM requesters ORDER BY name OFFSET :skip LIMIT :limit
""")
UPDATE_SQL = """
    UPDATE requesters SET {sets} WHERE requester_id = :rid
    RETURNING requester_id, name, requester_type, verified_flag, contact_phone, contact_email
"""


def mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return phone
    digits = [c for c in phone if c.isdigit()]
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + "".join(digits[-4:])


def mask_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None if not email else "***"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _full(row) -> dict:
    return {**dict(row), "contact_masked": False}


def _masked(row) -> dict:
    d = dict(row)
    d["contact_phone"], d["contact_email"] = mask_phone(d["contact_phone"]), mask_email(d["contact_email"])
    d["contact_masked"] = True
    return d


async def _read(db: AsyncSession, sql, params) -> list:
    try:
        rows = (await db.execute(sql, params)).mappings().all()
        await db.commit()
        return rows
    except exc.DBAPIError as e:
        await db.rollback()
        if _pg_code(e) == "42501":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not permitted to view requester profiles.")
        raise


async def get_profile(db: AsyncSession, requester_id: uuid.UUID, user) -> dict:
    if user.role not in ("coordinator", "requester"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not permitted to view requester profiles.")
    rows = await _read(db, DETAIL_SQL, {"rid": requester_id})
    if not rows:   # requester asking for someone else: RLS hides the row
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requester not found.")
    return _full(rows[0])


async def list_profiles(db: AsyncSession, user, skip: int = 0, limit: int = 100) -> list:
    if user.role != "coordinator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a coordinator can list requesters.")
    return [_masked(r) for r in await _read(db, LIST_SQL, {"skip": skip, "limit": limit})]


async def update_own_contact(db: AsyncSession, payload, user) -> dict:
    if user.role != "requester":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a requester can update its own contact details.")
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if k in ("contact_phone", "contact_email")}
    if not fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to update.")
    sets = ", ".join(f"{k} = :{k}" for k in fields)          # keys are whitelisted above
    try:
        row = (await db.execute(text(UPDATE_SQL.format(sets=sets)), {**fields, "rid": user.sub})).mappings().first()
        await db.commit()
    except exc.DBAPIError as e:
        await db.rollback()
        code = _pg_code(e)
        if code == "42501":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not permitted to change these fields.")
        if code in ("23514", "22001", "23502"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Rejected by database constraints.")
        raise
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requester not found.")
    return _full(row)
