"""Authentication / authorization dependencies.

* No token, a malformed / tampered / expired token, an unknown role, or an
  account that is no longer active -> 401 (there is no anonymous or demo
  fallback identity).
* Wrong role for an operation -> 403 (require_role / require_coordinator).
* get_db_with_rls returns a session whose EVERY transaction runs as the
  caller's PostgreSQL role (api_coordinator / api_owner / api_requester) with
  the subject id in jwt.claims.*, so GRANTs and RLS policies enforce access
  even if an API-level check were missing.
"""
import uuid
from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import auth_session, claims_for, role_session
from app.schemas.schemas import TokenData
from app.security.jwt import ExpiredSignatureError, InvalidTokenError, decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

VALID_ROLES = ("coordinator", "owner", "requester")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def _uuid(value) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


async def account_is_active(user_id: str, role: str, subject: str) -> bool:
    """fn_auth_session (SECURITY DEFINER, EXECUTE granted only to api_auth)."""
    async with auth_session() as s:
        return bool((await s.execute(
            text("SELECT fn_auth_session(CAST(:u AS uuid), :r, CAST(:s AS uuid))"),
            {"u": user_id, "r": role, "s": subject},
        )).scalar())


async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> TokenData:
    if not token:
        raise _unauthorized("Not authenticated")
    try:
        claims = decode_access_token(token)
    except ExpiredSignatureError:
        raise _unauthorized("Authentication token has expired")
    except InvalidTokenError:
        raise _unauthorized("Invalid authentication token")
    role = claims.get("role")
    subject, user_id = _uuid(claims.get("sub")), _uuid(claims.get("uid"))
    if role not in VALID_ROLES or subject is None or user_id is None:
        raise _unauthorized("Invalid authentication token")
    if not await account_is_active(user_id, role, subject):
        raise _unauthorized("Account is disabled or no longer exists")
    return TokenData(sub=subject, role=role, user_id=user_id, name=claims.get("name"))


async def get_db_with_rls(current_user: TokenData = Depends(get_current_user)) -> AsyncGenerator[AsyncSession, None]:
    async with role_session(f"api_{current_user.role}", claims_for(current_user.role, current_user.sub)) as session:
        yield session


def require_role(*roles: str, detail: Optional[str] = None):
    allowed = frozenset(roles)

    async def _dependency(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        if current_user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=detail or f"This operation requires one of the roles: {', '.join(sorted(allowed))}.")
        return current_user

    return _dependency


require_coordinator = require_role(
    "coordinator",
    detail="Only a coordinator can perform this operation (matching, allocation, dispatch, confirmation, audit).",
)
require_manager = require_role(
    "coordinator", "owner",
    detail="Only coordinators and resource owners can view or manage resources.",
)
require_request_party = require_role(
    "coordinator", "requester",
    detail="Resource owners are not permitted to view or create emergency requests.",
)
