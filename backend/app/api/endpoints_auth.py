"""Login: username + password -> signed JWT.

Credentials live in app_users (migration 0015) and are reachable only through
SECURITY DEFINER functions executable by the api_auth role, which can read no
table. Passwords are PBKDF2-SHA256 (app/security/passwords.py). Five
consecutive failures lock the account for 15 minutes (fn_auth_record_login).

There is no endpoint that issues a token without a password check (the old
/auth/demo-token and the role-picking /auth/token were removed). Seeded demo
accounts go through exactly this path.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import auth_session
from app.schemas.schemas import AuthUserOut, LoginRequest, TokenData, TokenResponse
from app.security.jwt import create_access_token
from app.security.passwords import dummy_verify, verify_password

router = APIRouter()

INVALID_CREDENTIALS = "Invalid username or password"


def _invalid() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS,
                         headers={"WWW-Authenticate": "Bearer"})


async def authenticate(username: str, password: str) -> TokenResponse:
    async with auth_session() as s:
        row = (await s.execute(text("SELECT * FROM fn_auth_credentials(:u)"), {"u": username})).mappings().first()
        if row is None:
            await run_in_threadpool(dummy_verify, password)     # same cost as a wrong password
            raise _invalid()
        locked_until = row["locked_until"]
        if locked_until is not None and locked_until > datetime.now(timezone.utc):
            await run_in_threadpool(dummy_verify, password)
            retry = max(1, int((locked_until - datetime.now(timezone.utc)).total_seconds()))
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="Too many failed login attempts. Try again later.",
                                headers={"Retry-After": str(retry)})
        ok = await run_in_threadpool(verify_password, password, row["password_hash"])
        if not ok:
            await s.execute(text("SELECT fn_auth_record_login(:u, false)"), {"u": row["user_id"]})
            await s.commit()
            raise _invalid()
        if not row["is_active"]:
            raise _invalid()
        await s.execute(text("SELECT fn_auth_record_login(:u, true)"), {"u": row["user_id"]})
        await s.commit()

    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(subject=row["subject_id"], role=row["role"], expires_delta=expires,
                                user_id=row["user_id"], name=row["display_name"])
    return TokenResponse(
        access_token=token,
        expires_in=int(expires.total_seconds()),
        user=AuthUserOut(user_id=row["user_id"], subject_id=row["subject_id"], role=row["role"],
                         display_name=row["display_name"]),
    )


@router.post("/login", response_model=TokenResponse)
async def login(credentials: LoginRequest):
    """JSON login used by the web app."""
    return await authenticate(credentials.username, credentials.password)


@router.post("/token", response_model=TokenResponse)
async def login_form(form: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password-flow form login (used by the Swagger 'Authorize' button)."""
    if not (3 <= len(form.username) <= 64) or not (1 <= len(form.password) <= 256):
        raise _invalid()
    return await authenticate(form.username.strip(), form.password)


@router.get("/me", response_model=AuthUserOut)
async def me(current_user: TokenData = Depends(get_current_user)):
    """The authenticated identity (token validated, account re-checked as active)."""
    return AuthUserOut(user_id=current_user.user_id, subject_id=current_user.sub, role=current_user.role,
                       display_name=current_user.name or "")
