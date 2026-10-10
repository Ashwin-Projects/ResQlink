"""Login: username + password -> signed JWT.

Credentials live in app_users (migration 0015) and are reachable only through
SECURITY DEFINER functions executable by the api_auth role, which can read no
table. Passwords are PBKDF2-SHA256 (app/security/passwords.py). Five
consecutive failures lock the account for 15 minutes (fn_auth_record_login).

There is no endpoint that issues a token without a password check (the old
/auth/demo-token and the role-picking /auth/token were removed). Seeded demo
accounts go through exactly this path.

POST /register (public) creates requester accounts (active) and resource-owner
accounts (inactive until a coordinator verifies them) through fn_auth_register
(migration 0016). Coordinator accounts cannot be self-registered.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import exc, text
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import auth_session
from app.schemas.schemas import AuthUserOut, LoginRequest, RegisterRequest, RegisterResponse, TokenData, TokenResponse
from app.security.jwt import create_access_token
from app.security.passwords import dummy_verify, hash_password, verify_password
from app.services.request_intake import _pg_code

logger = logging.getLogger(__name__)
router = APIRouter()

INVALID_CREDENTIALS = "Invalid username or password"


def _invalid() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS,
                         headers={"WWW-Authenticate": "Bearer"})


ROLE_LABELS = {"requester": "Requester", "owner": "Resource Owner", "coordinator": "Coordinator"}


async def authenticate(username: str, password: str, expected_role: Optional[str] = None) -> TokenResponse:
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
        # Both checks below run only after a correct password, so they reveal
        # nothing to someone who does not hold the credentials.
        if not row["is_active"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=(
                "This account is not active. New resource-owner accounts can sign in once a coordinator "
                "has verified the organisation; otherwise contact a coordinator."))
        if expected_role is not None and expected_role != row["role"]:
            # No token is issued and nothing is recorded: the selected role is
            # only checked against the account, never used to grant access.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=(
                f"This account is a {ROLE_LABELS.get(row['role'], row['role'])} account, not "
                f"{ROLE_LABELS.get(expected_role, expected_role)}. Select the matching role to sign in."))
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
    """JSON login used by the web app. `expected_role` (optional) is the role
    chosen on the sign-in screen; it must match the account or no token is issued."""
    return await authenticate(credentials.username, credentials.password, credentials.expected_role)


REGISTER_SQL = text("""
    SELECT user_id, subject_id, role, is_active
    FROM fn_auth_register(:role, :username, :password_hash, :display_name, :phone, :email, :owner_type)
""")


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest):
    """Public sign-up for requesters (active immediately) and resource owners
    (pending until a coordinator verifies the organisation). Coordinator
    accounts are never self-created: 403. The account's role is fixed by
    fn_auth_register (migration 0016), which refuses any other role itself."""
    if body.role == "coordinator":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=(
            "Coordinator accounts cannot be created by sign-up. Coordinator access is granted by an "
            "administrator to authorised emergency-management staff."))
    password_hash = await run_in_threadpool(hash_password, body.password)
    try:
        async with auth_session() as s:
            row = (await s.execute(REGISTER_SQL, {
                "role": body.role, "username": body.username, "password_hash": password_hash,
                "display_name": body.display_name, "phone": body.contact_phone, "email": body.contact_email,
                "owner_type": body.owner_type,
            })).mappings().one()
            await s.commit()
    except exc.DBAPIError as e:
        code = _pg_code(e)
        if code == "23505":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That username is already taken.")
        if code in ("23514", "22001"):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Some details are not in an accepted format.")
        if code == "42501":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Self-registration is not available for this role.")
        logger.exception("Registration failed (SQLSTATE %s)", code)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed; please try again later.")

    active = bool(row["is_active"])
    return RegisterResponse(
        user_id=row["user_id"], username=body.username, role=row["role"],
        status="active" if active else "pending_approval",
        message=("Account created. You can sign in now." if active else
                 "Account created and awaiting verification. A coordinator must verify your organisation "
                 "before you can sign in."),
    )


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
