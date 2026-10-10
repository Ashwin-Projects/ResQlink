"""Signed access tokens (PyJWT, HS256 by default).

Claims:
    sub   subject entity id the database policies use (requester_id /
          owner_id / system_users.user_id)
    uid   app_users.user_id (re-checked against the database on every request
          via fn_auth_session, so a deactivated account stops working at once)
    role  requester | owner | coordinator
    name  display name (UI only, never used for authorization)
    iat / nbf / exp, iss, aud, jti

decode_access_token() requires every claim above, a matching issuer and
audience, the configured algorithm only (no "none", no algorithm switching)
and an unexpired token.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from app.core.config import settings

ISSUER = "resqlink-api"
AUDIENCE = "resqlink-web"
REQUIRED_CLAIMS = ["sub", "uid", "role", "iat", "nbf", "exp", "iss", "aud", "jti"]

InvalidTokenError = jwt.InvalidTokenError
ExpiredSignatureError = jwt.ExpiredSignatureError


def create_access_token(
    subject: Any,
    role: str,
    expires_delta: Optional[timedelta] = None,
    *,
    user_id: Optional[Any] = None,
    name: Optional[str] = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta if expires_delta is not None else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    claims = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "nbf": now,
        "exp": expire,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "jti": str(uuid.uuid4()),
    }
    if user_id is not None:
        claims["uid"] = str(user_id)
    if name:
        claims["name"] = name
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.ExpiredSignatureError / jwt.InvalidTokenError."""
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": REQUIRED_CLAIMS},
        leeway=10,
    )
