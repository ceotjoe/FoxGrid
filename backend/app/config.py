from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from FOXGRID_* environment variables or `.env`."""

    model_config = SettingsConfigDict(env_prefix="FOXGRID_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://foxgrid:foxgrid@localhost:5432/foxgrid"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str  # required, no default on purpose
    jwt_ttl_hours: int = 72
    position_min_interval_s: int = 5
    recompute_debounce_ms: int = 500
    recompute_max_wait_ms: int = 2000
    track_purge_interval_s: int = 3600
    # Browser clients (Flutter web) need CORS. Auth is a bearer token (no cookies), so '*' is safe;
    # restrict to your web origin in production.
    # Push via Firebase Cloud Messaging (HTTP v1). Without credentials pushes are only logged.
    fcm_project_id: str | None = None
    fcm_credentials_file: str | None = None
    cors_origins: list[str] = ["*"]
