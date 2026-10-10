import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import router as api_router
from app.api.endpoints_matching import router as matching_router
from app.api.endpoints_audit import router as audit_router
from app.api.endpoints_auth import router as auth_router
from app.api.endpoints_dashboard import router as dashboard_router
from app.api.endpoints_map import router as map_router
from app.api.endpoints_hazards import router as hazards_router
from app.api.endpoints_evaluation import router as evaluation_router
from app.api.endpoints_allocations import router as allocations_router
from app.api.endpoints_requesters import router as requesters_router
from app.api.deps import get_current_user, require_coordinator
from app.core.config import settings, DEFAULT_SECRET_KEY
from app.db.session import database_login_is_privileged

logger = logging.getLogger("resqlink.security")

app = FastAPI(title=settings.PROJECT_NAME)


@app.on_event("startup")
async def _security_startup_checks() -> None:
    if settings.SECRET_KEY == DEFAULT_SECRET_KEY or len(settings.SECRET_KEY) < 32:
        logger.warning("SECRET_KEY is the development default or shorter than 32 characters; "
                       "set a strong SECRET_KEY before any non-local deployment.")
    if await database_login_is_privileged():
        logger.warning("DATABASE_URL logs in as a superuser / BYPASSRLS role. Every transaction still runs "
                       "under SET LOCAL ROLE api_*, but use the unprivileged resqlink_app login (see README).")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME}

# Public: only /health and the login endpoints. Every other router requires a
# valid token (router-level dependency) in addition to its per-endpoint role checks.
AUTHENTICATED = [Depends(get_current_user)]
COORDINATOR_ONLY = [Depends(require_coordinator)]

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=AUTHENTICATED)
app.include_router(map_router, prefix="/api/v1/map", tags=["map"], dependencies=AUTHENTICATED)
app.include_router(hazards_router, prefix="/api/v1/hazards", tags=["hazards"], dependencies=COORDINATOR_ONLY)
app.include_router(evaluation_router, prefix="/api/v1/evaluation", tags=["evaluation"], dependencies=AUTHENTICATED)
app.include_router(api_router, prefix="/api/v1", tags=["core"], dependencies=AUTHENTICATED)
app.include_router(requesters_router, prefix="/api/v1", tags=["requesters"], dependencies=AUTHENTICATED)
app.include_router(matching_router, prefix="/api/v1/match", tags=["matching"], dependencies=COORDINATOR_ONLY)
app.include_router(allocations_router, prefix="/api/v1", tags=["allocations"], dependencies=COORDINATOR_ONLY)
app.include_router(audit_router, prefix="/api/v1/audit", tags=["audit"], dependencies=COORDINATOR_ONLY)
