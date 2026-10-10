from pydantic import field_validator
from pydantic_settings import BaseSettings

DEFAULT_SECRET_KEY = "dev-secret-key-change-in-production-12345"

class Settings(BaseSettings):
    PROJECT_NAME: str = "ResQLink Emergency Engine"
    # The API logs in as the unprivileged resqlink_app role (migration 0015).
    DATABASE_URL: str = "postgresql+asyncpg://resqlink_app:resqlink_app_password@localhost:5432/resqlink"
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    # Outbox event processor + reservation lease expiry, run inside the API
    # process (app/workers/supervisor.py). Off by default: enabling them makes
    # the worker process every unprocessed event already in event_outbox.
    # Set BACKGROUND_WORKERS_ENABLED=true to run them.
    BACKGROUND_WORKERS_ENABLED: bool = False
    OUTBOX_POLL_SECONDS: float = 5.0
    LEASE_EXPIRY_POLL_SECONDS: float = 10.0

    @field_validator("ALGORITHM")
    @classmethod
    def _hmac_only(cls, v: str) -> str:
        # Never "none" and never an asymmetric algorithm keyed by a shared secret.
        if v not in ("HS256", "HS384", "HS512"):
            raise ValueError("ALGORITHM must be HS256, HS384 or HS512")
        return v

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def _bounded_lifetime(cls, v: int) -> int:
        if not 1 <= v <= 24 * 60:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 1440")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

